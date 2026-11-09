from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo
import sqlite3

import pytest
from fastapi.testclient import TestClient
from src.api import create_app
from src.collectors.cron import CronCollector
from src.manage_db import backup, restore
from src.services.annotations import AnnotationStore

PEER = ('192.168.0.2', 12345)
COMMAND = '/example/periodic-task --token=PRIVATE_MARKER'
ROWS = [f'0 3 * * * {COMMAND}', f'0 6 * * * {COMMAND}']
NOW = datetime(2026, 11, 9, tzinfo=ZoneInfo('Asia/Tokyo'))


def tasks_for(path, rows):
    path.write_text('\n'.join(rows))
    return CronCollector(path, 'Asia/Tokyo').collect(NOW).tasks


def v1_database(path, entries):
    """Freeze the released schema, including the absence of identity metadata."""
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript('''
            CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
            INSERT INTO metadata VALUES(1,100);
            CREATE TABLE definitions (definition_id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL,presence TEXT NOT NULL,last_seen_at TEXT);
            CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,name_key TEXT NOT NULL UNIQUE,version INTEGER NOT NULL);
            CREATE TABLE definition_tags (definition_id TEXT NOT NULL REFERENCES definitions ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags ON DELETE CASCADE,PRIMARY KEY(definition_id,tag_id));
            PRAGMA user_version=1;
        ''')
        conn.execute('INSERT INTO tags VALUES(1,?,?,1)', ('保守', '保守'))
        for number, (key, name, tagged) in enumerate(entries, 2):
            conn.execute('INSERT INTO definitions VALUES(?,?,?,?,?)', (key, name, number, 'present', '2026-11-07T00:00:00+09:00'))
            if tagged:
                conn.execute('INSERT INTO definition_tags VALUES(?,1)', (key,))
        conn.commit()


def test_v1_annotations_migrate_atomically_with_backup_and_restart(tmp_path):
    cron, db = tmp_path/'cron', tmp_path/'qsv.sqlite3'
    collected = tasks_for(cron, ROWS)
    keys = {t._legacy_definition_id for t in collected}
    v1_database(db, [(key, '定期保守', True) for key in keys])
    with TestClient(create_app(cron, allowed_proxy_ips=PEER[0], db_path=db), client=PEER) as client:
        data = client.get('/api/schedules').json()
        assert [t['name'] for t in data['tasks']] == ['定期保守'] * 2
        assert [t['duplicate_count'] for t in data['tasks']] == [2, 2]
        assert len({t['definition_id'] for t in data['tasks']}) == 1
        assert all(t['tags'][0]['name'] == '保守' for t in data['tasks'])
        saved = client.get('/api/annotations').json()
        assert len(saved) == 1 and saved[0]['definition_id'].startswith('cron-v2-')
        original = data['tasks'][0]
        cron.write_text(f'0 12 * * 1 {COMMAND}')
        assert client.post('/api/refresh').status_code == 200
        changed = client.get('/api/schedules').json()['tasks'][0]
        assert changed['definition_id'] == original['definition_id']
        assert changed['name'] == '定期保守' and changed['annotation_version'] == original['annotation_version']
    backups = list(tmp_path.glob('qsv.sqlite3.before-v2-*.sqlite3'))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 1
        assert {r[0] for r in conn.execute('SELECT definition_id FROM definitions')} == keys
        assert conn.execute('SELECT COUNT(*) FROM definition_tags').fetchone()[0] == 2
    with TestClient(create_app(cron, allowed_proxy_ips=PEER[0], db_path=db), client=PEER) as client:
        assert client.get('/api/schedules').json()['tasks'][0]['name'] == '定期保守'
    assert len(list(tmp_path.glob('qsv.sqlite3.before-v2-*.sqlite3'))) == 1
    for file in tmp_path.glob('*.sqlite3*'):
        assert 'PRIVATE_MARKER' not in file.read_bytes().decode('utf-8', errors='ignore')


@pytest.mark.parametrize('names,tags', [(('朝','夜'),(True,True)), (('同じ','同じ'),(True,False))])
def test_conflicting_old_annotations_remain_and_require_explicit_choice(tmp_path, names, tags):
    cron, db = tmp_path/'cron', tmp_path/'qsv.sqlite3'
    collected = tasks_for(cron, ROWS)
    old = [t._legacy_definition_id for t in collected]
    v1_database(db, [(old[i], names[i], tags[i]) for i in range(2)])
    with TestClient(create_app(cron, allowed_proxy_ips=PEER[0], db_path=db), client=PEER) as client:
        assert client.get('/api/schedules').json()['identity_conflict_count'] == 1
        data = client.get('/api/schedules').json()['tasks']
        assert all(t['display_name'] == '' for t in data)
        assert all(any('異なる表示名' in warning for warning in t['warnings']) for t in data)
        saved = {a['definition_id']: a for a in client.get('/api/annotations').json()}
        assert {saved[key]['display_name'] for key in old} == set(names)
        source, target = saved[old[0]], data[0]
        assert client.post('/api/annotations/copy', json={
            'source_id': source['definition_id'], 'target_id': target['definition_id'],
            'source_version': source['version'], 'target_version': target['annotation_version'],
        }).status_code == 200
        assert client.get('/api/schedules').json()['identity_conflict_count'] == 0
        chosen = client.get('/api/schedules').json()['tasks']
        assert [t['name'] for t in chosen] == [names[0]] * 2
        assert all(not any('異なる表示名' in warning for warning in t['warnings']) for t in chosen)
        assert client.post('/api/refresh').status_code == 200
        assert all(t['name'] == names[0] for t in client.get('/api/schedules').json()['tasks'])
        # Unchosen historical values remain available; never merge or discard.
        saved = {a['definition_id']: a for a in client.get('/api/annotations').json()}
        assert saved[old[1]]['display_name'] == names[1]


def test_already_detached_v1_record_is_retained_for_manual_copy(tmp_path):
    cron, db = tmp_path/'cron', tmp_path/'qsv.sqlite3'
    old = tasks_for(cron, ROWS[:1])[0]._legacy_definition_id
    v1_database(db, [(old, '保持する名前', True)])
    cron.write_text(f'0 9 * * * {COMMAND}')
    with TestClient(create_app(cron, allowed_proxy_ips=PEER[0], db_path=db), client=PEER) as client:
        current = client.get('/api/schedules').json()['tasks'][0]
        assert not current['display_name']
        saved = {a['definition_id']: a for a in client.get('/api/annotations').json()}[old]
        assert saved['display_name'] == '保持する名前' and saved['presence'] == 'absent'
        assert client.post('/api/annotations/copy', json={
            'source_id': old, 'target_id': current['definition_id'],
            'source_version': saved['version'], 'target_version': current['annotation_version'],
        }).status_code == 200
        cron.write_text(f'30 10 * * 0 {COMMAND}')
        client.post('/api/refresh')
        assert client.get('/api/schedules').json()['tasks'][0]['name'] == '保持する名前'


def test_explicit_reset_prevents_old_settings_from_reappearing(tmp_path):
    cron, db = tmp_path/'cron', tmp_path/'qsv.sqlite3'
    collected = tasks_for(cron, ROWS)
    old = [t._legacy_definition_id for t in collected]
    v1_database(db, [(old[0], '朝', True), (old[1], '夜', True)])
    with TestClient(create_app(cron, allowed_proxy_ips=PEER[0], db_path=db), client=PEER) as client:
        task = client.get('/api/schedules').json()['tasks'][0]
        assert client.request('DELETE', '/api/annotations/'+task['definition_id'],json={'version':task['annotation_version']}).status_code == 200
        client.post('/api/refresh')
        current = client.get('/api/schedules').json()['tasks']
        assert all(t['display_name'] == '' and t['tags'] == [] for t in current)
        assert all(not any('異なる表示名' in warning for warning in t['warnings']) for t in current)


def test_reset_before_a_legacy_match_also_blocks_automatic_restoration(tmp_path):
    cron, db = tmp_path/'cron', tmp_path/'qsv.sqlite3'
    old = tasks_for(cron, ROWS[:1])[0]._legacy_definition_id
    v1_database(db, [(old, '旧設定', True)])
    cron.write_text(f'0 9 * * * {COMMAND}')  # v1 source currently cannot be mapped
    with TestClient(create_app(cron, allowed_proxy_ips=PEER[0], db_path=db), client=PEER) as client:
        task = client.get('/api/schedules').json()['tasks'][0]
        client.request('DELETE', '/api/annotations/'+task['definition_id'],json={'version':task['annotation_version']})
        cron.write_text(ROWS[0])  # The old v1 fingerprint now matches again.
        client.post('/api/refresh')
        assert client.get('/api/schedules').json()['tasks'][0]['display_name'] == ''
        assert {a['definition_id']:a for a in client.get('/api/annotations').json()}[old]['display_name'] == '旧設定'


def test_existing_v2_values_are_not_overwritten_during_upgrade(tmp_path):
    cron, db = tmp_path/'cron', tmp_path/'qsv.sqlite3'
    task = tasks_for(cron, ROWS[:1])[0]
    v1_database(db, [(task._legacy_definition_id,'旧設定',True),(task.definition_id,'現設定',False)])
    with TestClient(create_app(cron, allowed_proxy_ips=PEER[0], db_path=db), client=PEER) as client:
        current = client.get('/api/schedules').json()['tasks'][0]
        assert current['display_name'] == '現設定' and current['tags'] == []
        assert any('異なる表示名' in warning for warning in current['warnings'])


def test_upgrade_failure_rolls_back_schema_and_preserves_backup(tmp_path, monkeypatch):
    db = tmp_path/'qsv.sqlite3'
    v1_database(db, [('legacy', '保持', True)])
    connect = sqlite3.connect
    def guarded(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_authorizer(lambda action, name, *unused: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and name == 'identity_resolutions' else sqlite3.SQLITE_OK)
        return conn
    monkeypatch.setattr(sqlite3, 'connect', guarded)
    with pytest.raises(sqlite3.DatabaseError):
        AnnotationStore(db).initialize()
    with closing(connect(db)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 1
        assert conn.execute('SELECT display_name FROM definitions').fetchone()[0] == '保持'
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='identity_migrations'").fetchall()
    assert len(list(tmp_path.glob('qsv.sqlite3.before-v2-*.sqlite3'))) == 1


def test_v1_backup_can_be_restored_then_upgraded(tmp_path):
    db, saved = tmp_path/'qsv.sqlite3', tmp_path/'saved.sqlite3'
    v1_database(db, [('legacy','保持',True)])
    backup(db, saved)
    store = AnnotationStore(db); store.initialize()
    restore(saved, db, offline=True)
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 1
    store.initialize()
    assert store.snapshot()['annotations']['legacy']['display_name'] == '保持'

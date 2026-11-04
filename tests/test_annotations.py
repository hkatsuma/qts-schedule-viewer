from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient
from src.api import create_app
from src.services.annotations import AnnotationStore, AnnotationError

PEER = ('192.168.0.2', 12345)
ROWS = '0 3 * * * /example/one --token=PRIVATE_MARKER\n0 3 * * * /example/one --token=PRIVATE_MARKER\n0 4 * * * /example/two\n'


def setup(tmp_path):
    path = tmp_path / 'cron'
    path.write_text(ROWS)
    db = tmp_path / 'annotations.sqlite3'
    return path, db, create_app(path, allowed_proxy_ips=PEER[0], db_path=db)


def save(client, task, name, tags=()):
    return client.put('/api/annotations/' + task['definition_id'], json={
        'version': task['annotation_version'], 'display_name': name, 'tag_ids': list(tags)})


def test_annotations_duplicates_filters_and_restart(tmp_path):
    path, db, app = setup(tmp_path)
    with TestClient(app, client=PEER) as client:
        a = client.post('/api/tags', json={'name': '保守'}).json()
        b = client.post('/api/tags', json={'name': '夜間'}).json()
        tasks = client.get('/api/schedules').json()['tasks']
        assert save(client, tasks[0], '=Maintenance', [a['id'], b['id']]).status_code == 200
        assert save(client, tasks[2], '別ジョブ', [b['id']]).status_code == 200
        data = client.get('/api/schedules').json()
        assert [t['name'] for t in data['tasks']] == ['=Maintenance', '=Maintenance', '別ジョブ']
        assert len({t['annotation_version'] for t in data['tasks'][:2]}) == 1
        assert 'PRIVATE_MARKER' not in str(data)
        assert all('PRIVATE_MARKER' not in f.read_bytes().decode('utf-8', errors='ignore') for f in db.parent.glob('annotations.sqlite3*'))
        assert len(client.get('/api/schedules', params={'q': 'Maintenance'}).json()['tasks']) == 2
        params = [('tag', a['id']), ('tag', b['id']), ('tag_match', 'all')]
        assert len(client.get('/api/schedules', params=params).json()['tasks']) == 2
        assert len(client.get('/api/schedules', params=[('tag', a['id']), ('tag', b['id'])]).json()['tasks']) == 3
        assert client.get('/api/schedules?tag=999').json()['tasks'] == []
        assert client.get('/api/schedules?tag_match=invalid').status_code == 422
        assert len(client.get('/api/timeline', params=params + [('start', '2026-11-02')]).json()['events']) == 14
        month = client.get('/api/month', params=params + [('month', '2026-11-01')]).json()
        assert len(month['days']) == 60
        assert {d['name'] for d in month['days']} == {'=Maintenance'}
        csv = client.get('/api/export.csv', params=params).text
        assert "'=Maintenance" in csv and '別ジョブ' not in csv and '保守' in csv and 'PRIVATE_MARKER' not in csv
    # A fresh app instance (container recreation) reuses the same DB.
    with TestClient(create_app(path, allowed_proxy_ips=PEER[0], db_path=db), client=PEER) as client:
        assert [t['name'] for t in client.get('/api/schedules').json()['tasks']][:2] == ['=Maintenance'] * 2
        assert len(client.get('/api/tags').json()) == 2
    assert path.read_text() == ROWS


def test_tag_rename_delete_validation_and_annotation_conflicts(tmp_path):
    _, _, app = setup(tmp_path)
    with TestClient(app, client=PEER) as client:
        a = client.post('/api/tags', json={'name': ' Night '}).json()
        assert a['name'] == 'Night'
        assert client.post('/api/tags', json={'name': 'NIGHT'}).status_code == 409
        for name in (' ', 'x' * 41, 'a\nb', '\u200b'):
            assert client.post('/api/tags', json={'name': name}).status_code == 422
        task = client.get('/api/schedules').json()['tasks'][0]
        assert save(client, task, '名前', [a['id']]).status_code == 200
        assert save(client, task, '競合').status_code == 409
        current = client.get('/api/schedules').json()['tasks'][0]
        renamed = client.put(f"/api/tags/{a['id']}", json={'version': a['version'], 'name': '夜間'}).json()
        assert renamed['id'] == a['id']
        assert client.get('/api/schedules', params={'tag': a['id']}).json()['tasks'][0]['tags'][0]['name'] == '夜間'
        assert client.request('DELETE', f"/api/tags/{a['id']}", json={'version': a['version']}).status_code == 409
        assert client.request('DELETE', f"/api/tags/{a['id']}", json={'version': renamed['version']}).status_code == 200
        assert save(client, current, '古い選択', [a['id']]).status_code == 409
        refreshed = client.get('/api/schedules').json()['tasks'][0]
        assert refreshed['tags'] == []
        assert save(client, refreshed, '未登録', [999]).status_code == 422
        assert save(client, refreshed, '重複', [1, 1]).status_code == 422
        assert client.request('DELETE', '/api/annotations/' + refreshed['definition_id'], json={'version': refreshed['annotation_version']}).status_code == 200
        reset = client.get('/api/schedules').json()['tasks'][0]
        assert reset['display_name'] == '' and reset['name'] == reset['original_name']


def test_absence_partial_failure_return_and_explicit_copy(tmp_path):
    path, _, app = setup(tmp_path)
    with TestClient(app, client=PEER) as client:
        tag = client.post('/api/tags', json={'name': '保持'}).json()
        source = client.get('/api/schedules').json()['tasks'][0]
        assert save(client, source, '元の注釈', [tag['id']]).status_code == 200
        key = source['definition_id']
        path.write_text('@reboot /example/unsupported\n')
        client.post('/api/refresh')
        annotations = {a['definition_id']: a for a in client.get('/api/annotations').json()}
        assert annotations[key]['presence'] == 'unknown'
        path.unlink()
        client.post('/api/refresh')
        assert {a['definition_id']: a for a in client.get('/api/annotations').json()}[key]['presence'] == 'unknown'
        path.write_text('0 5 * * * /example/replacement')
        client.post('/api/refresh')
        annotations = {a['definition_id']: a for a in client.get('/api/annotations').json()}
        assert annotations[key]['presence'] == 'absent'
        source_ann = annotations[key]
        target = client.get('/api/schedules').json()['tasks'][0]
        assert target['display_name'] == '' and target['tags'] == []
        payload = {'source_id': key, 'target_id': target['definition_id'], 'source_version': source_ann['version'], 'target_version': target['annotation_version']}
        assert client.post('/api/annotations/copy', json=payload).status_code == 200
        copied = client.get('/api/schedules').json()['tasks'][0]
        assert copied['name'] == '元の注釈' and copied['tags'][0]['id'] == tag['id']
        assert client.post('/api/annotations/copy', json=payload).status_code == 409
        payload['target_version'] = copied['annotation_version']
        assert client.post('/api/annotations/copy', json=payload).status_code == 409
        assert client.post('/api/annotations/copy', json=payload | {'overwrite': True}).status_code == 200
        path.write_text(ROWS)
        client.post('/api/refresh')
        restored = client.get('/api/schedules').json()['tasks'][0]
        assert restored['name'] == '元の注釈'
        assert restored['definition_id'] == key
        assert restored['annotation_version'] == source_ann['version']
        # Lost target / stale source version must fail rather than copying to a
        # row at a matching line number.
        assert client.post('/api/annotations/copy', json=payload | {'overwrite': True}).status_code == 409


@pytest.mark.parametrize('origin', ['https://evil.example', 'null', 'http://[', 'https://testserver.evil.example'])
def test_all_writes_reject_foreign_or_malformed_origins(tmp_path, origin):
    _, _, app = setup(tmp_path)
    with TestClient(app, client=PEER) as client:
        for method, route, payload in [
            ('POST', '/api/tags', {'name': '禁止'}),
            ('PUT', '/api/tags/1', {'version': 1, 'name': '禁止'}),
            ('DELETE', '/api/tags/1', {'version': 1}),
            ('PUT', '/api/annotations/unknown', {'version': 1}),
            ('DELETE', '/api/annotations/unknown', {'version': 1}),
            ('POST', '/api/annotations/copy', {}),
        ]:
            assert client.request(method, route, json=payload, headers={'Origin': origin}).status_code == 403
        assert client.get('/api/tags').json() == []


def test_write_peer_content_type_body_size_and_cli_origin_rules(tmp_path):
    _, _, app = setup(tmp_path)
    with TestClient(app, client=('192.168.0.99', 12345)) as client:
        for route in ('/api/tags', '/api/annotations', '/api/annotations/copy'):
            assert client.get(route, headers={'X-Forwarded-For': PEER[0]}).status_code == 403
            assert client.post(route, json={'name': '禁止'}, headers={'X-Forwarded-For': PEER[0]}).status_code == 403
    with TestClient(app, client=PEER) as client:
        assert client.post('/api/tags', content='{"name":"bad"}', headers={'Content-Type': 'text/plain'}).status_code == 415
        assert client.post('/api/tags', json={'name': 'x' * 17000}).status_code == 413
        assert client.post('/api/tags', json={'name': 'a'}, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        assert client.post('/api/tags', json={'name': 'HTTPS'}, headers={'Origin': 'https://testserver'}).status_code == 201
        assert client.post('/api/tags', json={'name': 'CLI'}).status_code == 201
        assert client.post('/api/tags', json={'name': '余分', 'path': '/etc/config/crontab'}).status_code == 422


def test_store_concurrent_writers_and_schema_guard(tmp_path):
    store = AnnotationStore(tmp_path / 'db.sqlite3')
    store.initialize()
    store.observe({'cron-v1-test'}, 'ok', datetime.now().isoformat())
    original = store.snapshot()['annotations']['cron-v1-test']
    def update(name):
        try:
            store.update('cron-v1-test', original['version'], name, [])
            return 200
        except AnnotationError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, ['one', 'two'])) == [200, 409]
    with sqlite3.connect(store.path) as conn:
        conn.execute('PRAGMA user_version=999')
    with pytest.raises(RuntimeError, match='スキーマ'):
        store.initialize()

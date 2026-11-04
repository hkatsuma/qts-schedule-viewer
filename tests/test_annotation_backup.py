import sqlite3
import pytest
from src.manage_db import backup, restore
from src.services.annotations import AnnotationStore


def test_online_backup_is_consistent_and_offline_restore_preserves_annotations(tmp_path):
    store = AnnotationStore(tmp_path / 'qsv.sqlite3')
    store.initialize()
    store.observe({'definition-a'}, 'ok', '2026-11-04T12:00:00+09:00')
    a = store.snapshot()['annotations']['definition-a']
    tag = store.create_tag('保守')
    store.update('definition-a', a['version'], 'バックアップの名前', [tag['id']])
    expected = store.snapshot()
    saved = tmp_path / 'backup.sqlite3'
    with store.connection(write=True) as writer:
        writer.execute('UPDATE definitions SET display_name=?', ('未コミット',))
        backup(store.path, saved)
    assert store.snapshot()['annotations']['definition-a']['display_name'] == '未コミット'
    assert not (tmp_path / 'backup.sqlite3-wal').exists()
    with pytest.raises(RuntimeError, match='停止'):
        restore(saved, store.path)
    restore(saved, store.path, offline=True)
    store.initialize()
    assert store.snapshot() == expected
    with pytest.raises(FileExistsError):
        backup(store.path, saved)
    with pytest.raises(RuntimeError, match='別のファイル'):
        backup(store.path, store.path)


def test_invalid_or_future_backups_never_replace_database(tmp_path):
    store = AnnotationStore(tmp_path / 'qsv.sqlite3')
    store.initialize()
    store.create_tag('保持')
    expected = store.snapshot()
    corrupt = tmp_path / 'corrupt.sqlite3'
    corrupt.write_text('not a database')
    with pytest.raises(sqlite3.Error):
        restore(corrupt, store.path, offline=True)
    future = tmp_path / 'future.sqlite3'
    with sqlite3.connect(future) as conn:
        conn.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError, match='スキーマ'):
        restore(future, store.path, offline=True)
    assert store.snapshot() == expected

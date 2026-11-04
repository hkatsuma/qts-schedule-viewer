"""Consistent annotation backups and explicitly offline restores."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
from src.services.annotations import SCHEMA_VERSION


def read_database(path):
    if not path.is_file():
        raise RuntimeError('DBファイルがありません')
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        if conn.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            raise RuntimeError('バックアップのスキーマに対応していません')
        if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('DBの整合性を確認できません')
        return conn
    except BaseException:
        conn.close()
        raise


def backup(source: Path, destination: Path):
    if source.resolve() == destination.resolve():
        raise RuntimeError('保存先には別のファイルを指定してください')
    with closing(read_database(source)) as source_conn:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        try:
            with closing(sqlite3.connect(destination)) as output:
                source_conn.backup(output)
                output.execute('PRAGMA journal_mode=DELETE')
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def restore(source: Path, destination: Path, *, offline=False):
    if not offline:
        raise RuntimeError('アプリを停止して --offline を指定してください')
    if source.resolve() == destination.resolve():
        raise RuntimeError('復元元とDBには別のファイルを指定してください')
    # Validate the backup before touching the live destination.
    conn = read_database(source)
    conn.close()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        with closing(sqlite3.connect(destination, timeout=5)) as current:
            if current.execute('PRAGMA user_version').fetchone()[0] > SCHEMA_VERSION:
                raise RuntimeError('新しいスキーマのDBには復元できません')
            if current.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                raise RuntimeError('DBが使用中です。アプリを停止してください')
    fd, temporary = tempfile.mkstemp(prefix='.qsv-restore-', dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary)
    temporary.unlink()
    try:
        backup(source, temporary)
        # The caller has explicitly stopped every writer. Remove crash remnants
        # only after checkpointing the old database, before replacing its file.
        for suffix in ('-wal', '-shm'):
            Path(str(destination) + suffix).unlink(missing_ok=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('backup', 'restore'))
    parser.add_argument('file', type=Path)
    parser.add_argument('--db', type=Path, default=Path(os.getenv('QSV_DB_PATH', '/data/qsv.sqlite3')))
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    try:
        if args.operation == 'backup':
            backup(args.db, args.file)
        else:
            restore(args.file, args.db, offline=args.offline)
    except (OSError, sqlite3.Error, RuntimeError) as error:
        parser.exit(1, f'DB操作に失敗しました: {error}\n')
    print('バックアップ完了' if args.operation == 'backup' else '復元完了')


if __name__ == '__main__':
    main()

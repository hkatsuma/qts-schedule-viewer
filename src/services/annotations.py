"""Instance-local annotation storage. Never persist collected commands or schedules."""
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3
import unicodedata

SCHEMA_VERSION = 1
MAX_TAGS = 200


class AnnotationError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


def clean_name(value: str, maximum: int, *, empty: bool = False) -> str:
    name = unicodedata.normalize('NFC', value).strip()
    if (not name and not empty) or len(name) > maximum or any(unicodedata.category(c).startswith('C') for c in name):
        raise AnnotationError(422, '名前の長さ・文字を確認してください')
    return name


class AnnotationStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self, *, write=False):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA temp_store=MEMORY')
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise RuntimeError('注釈DBのスキーマバージョンに対応していません')
            conn.execute('PRAGMA journal_mode=WAL')
        with self.connection(write=True) as conn:
            if version == 0:
                for statement in (
                    'CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)',
                    'INSERT INTO metadata VALUES(1, 0)',
                    '''CREATE TABLE definitions (
                        definition_id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '',
                        version INTEGER NOT NULL, presence TEXT NOT NULL, last_seen_at TEXT)''',
                    '''CREATE TABLE tags (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                        name_key TEXT NOT NULL UNIQUE, version INTEGER NOT NULL)''',
                    '''CREATE TABLE definition_tags (
                        definition_id TEXT NOT NULL REFERENCES definitions ON DELETE CASCADE,
                        tag_id INTEGER NOT NULL REFERENCES tags ON DELETE CASCADE,
                        PRIMARY KEY(definition_id, tag_id))''',
                ):
                    conn.execute(statement)
                conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        self.path.chmod(0o600)

    @staticmethod
    def _revision(conn):
        conn.execute('UPDATE metadata SET revision=revision+1 WHERE id=1')
        return conn.execute('SELECT revision FROM metadata WHERE id=1').fetchone()[0]

    @staticmethod
    def _definition(conn, definition_id, version=None):
        row = conn.execute('SELECT * FROM definitions WHERE definition_id=?', (definition_id,)).fetchone()
        if row is None:
            raise AnnotationError(404, '定義が見つかりません。再取得してください')
        if version is not None and row['version'] != version:
            raise AnnotationError(409, '他の操作で注釈が更新されました。読み直してください')
        return row

    def observe(self, definition_ids: set[str], status: str, at: str, *, stale=False):
        with self.connection(write=True) as conn:
            conn.execute('UPDATE definitions SET presence=?', ('absent' if status in ('ok', 'empty') and not stale else 'unknown',))
            observed = definition_ids if not stale and status in ('ok', 'empty', 'partial') else set()
            for key in sorted(observed):
                row = conn.execute('SELECT definition_id FROM definitions WHERE definition_id=?', (key,)).fetchone()
                if row is None:
                    conn.execute('INSERT INTO definitions(definition_id,version,presence,last_seen_at) VALUES(?,?,?,?)',
                                 (key, self._revision(conn), 'present', at))
                else:
                    conn.execute('UPDATE definitions SET presence=?, last_seen_at=? WHERE definition_id=?', ('present', at, key))
            # Retain every saved annotation, but not an ever-growing history of
            # unannotated definitions. New rows get a fresh global version, so
            # deleting an empty record cannot cause a stale-editor ABA update.
            conn.execute("""DELETE FROM definitions WHERE presence<>'present' AND display_name=''
                AND NOT EXISTS(SELECT 1 FROM definition_tags WHERE definition_id=definitions.definition_id)""")

    def snapshot(self):
        with self.connection() as conn:
            tags = [dict(row) for row in conn.execute('SELECT id,name,version FROM tags ORDER BY name_key,id')]
            by_id = {tag['id']: tag for tag in tags}
            annotations = {row['definition_id']: dict(row) | {'tags': []} for row in conn.execute('SELECT * FROM definitions')}
            for row in conn.execute('SELECT definition_id,tag_id FROM definition_tags ORDER BY tag_id'):
                annotations[row['definition_id']]['tags'].append(by_id[row['tag_id']])
            return {'tags': tags, 'annotations': annotations}

    def create_tag(self, name):
        name = clean_name(name, 40)
        with self.connection(write=True) as conn:
            if conn.execute('SELECT COUNT(*) FROM tags').fetchone()[0] >= MAX_TAGS:
                raise AnnotationError(422, 'タグは200件までです')
            try:
                cursor = conn.execute('INSERT INTO tags(name,name_key,version) VALUES(?,?,?)', (name, name.casefold(), self._revision(conn)))
            except sqlite3.IntegrityError:
                raise AnnotationError(409, '同じ名前のタグがあります') from None
            return dict(conn.execute('SELECT id,name,version FROM tags WHERE id=?', (cursor.lastrowid,)).fetchone())

    def change_tag(self, tag_id, version, name=None):
        if name is not None:
            name = clean_name(name, 40)
        with self.connection(write=True) as conn:
            tag = conn.execute('SELECT * FROM tags WHERE id=?', (tag_id,)).fetchone()
            if tag is None:
                raise AnnotationError(404, 'タグが見つかりません')
            if tag['version'] != version:
                raise AnnotationError(409, 'タグが更新されました。読み直してください')
            if name is None:
                keys = [r[0] for r in conn.execute('SELECT definition_id FROM definition_tags WHERE tag_id=?', (tag_id,))]
                for key in keys:
                    conn.execute('UPDATE definitions SET version=? WHERE definition_id=?', (self._revision(conn), key))
                conn.execute('DELETE FROM tags WHERE id=?', (tag_id,))
                return {'status': 'ok'}
            try:
                conn.execute('UPDATE tags SET name=?,name_key=?,version=? WHERE id=?', (name, name.casefold(), self._revision(conn), tag_id))
            except sqlite3.IntegrityError:
                raise AnnotationError(409, '同じ名前のタグがあります') from None
            return dict(conn.execute('SELECT id,name,version FROM tags WHERE id=?', (tag_id,)).fetchone())

    def update(self, definition_id, version, display_name, tag_ids, *, require_present=True):
        display_name = clean_name(display_name, 120, empty=True)
        ids = set(tag_ids)
        if len(ids) != len(tag_ids) or len(ids) > 64:
            raise AnnotationError(422, 'タグ指定を確認してください')
        with self.connection(write=True) as conn:
            row = self._definition(conn, definition_id, version)
            if require_present and row['presence'] != 'present':
                raise AnnotationError(409, '現在の定義を確認できません。再取得してください')
            existing = {r[0] for r in conn.execute('SELECT id FROM tags')}
            if not ids <= existing:
                raise AnnotationError(422, '削除済みのタグがあります。読み直してください')
            new_version = self._revision(conn)
            conn.execute('UPDATE definitions SET display_name=?,version=? WHERE definition_id=?', (display_name, new_version, definition_id))
            conn.execute('DELETE FROM definition_tags WHERE definition_id=?', (definition_id,))
            conn.executemany('INSERT INTO definition_tags VALUES(?,?)', [(definition_id, i) for i in sorted(ids)])
            return {'definition_id': definition_id, 'version': new_version}

    def copy(self, source_id, target_id, source_version, target_version, *, overwrite=False):
        if source_id == target_id:
            raise AnnotationError(422, '別の移行先を選択してください')
        with self.connection(write=True) as conn:
            source = self._definition(conn, source_id, source_version)
            target = self._definition(conn, target_id, target_version)
            if target['presence'] != 'present':
                raise AnnotationError(409, '移行先の定義を確認できません。再取得してください')
            ids = [r[0] for r in conn.execute('SELECT tag_id FROM definition_tags WHERE definition_id=?', (source_id,))]
            target_tags = conn.execute('SELECT 1 FROM definition_tags WHERE definition_id=? LIMIT 1', (target_id,)).fetchone()
            if not source['display_name'] and not ids:
                raise AnnotationError(422, 'コピーする注釈がありません')
            if not overwrite and (target['display_name'] or target_tags):
                raise AnnotationError(409, '移行先に注釈があります。置き換えを明示してください')
            version = self._revision(conn)
            conn.execute('UPDATE definitions SET display_name=?,version=? WHERE definition_id=?', (source['display_name'], version, target_id))
            conn.execute('DELETE FROM definition_tags WHERE definition_id=?', (target_id,))
            conn.executemany('INSERT INTO definition_tags VALUES(?,?)', [(target_id, i) for i in ids])
            return {'definition_id': target_id, 'version': version}

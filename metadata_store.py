"""Bundled SQLite metadata cache with automatic dbm/JSON upgrade and fallback."""
import json
import logging
import math
import os

LOG = logging.getLogger('walkman')
FIELDS = ('title', 'artist', 'album', 'mtime', 'size')


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as source:
            data = json.load(source)
        return {key: row for key, row in data.items() if isinstance(row, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _decode(raw):
    try:
        row = json.loads(raw.decode('utf-8'))
        return row if isinstance(row, dict) else None
    except (UnicodeError, ValueError, TypeError):
        return None


def _legacy_rows(dbm_path, json_path):
    """Read-only import: never delete or rewrite the user's old cache."""
    yield from _read_json(json_path).items()
    try:
        import dbm
        if not dbm.whichdb(dbm_path):
            return
        with dbm.open(dbm_path, 'r') as source:
            for key in source.keys():
                row = _decode(source[key])
                if row is not None:
                    yield key.decode('utf-8', 'surrogateescape'), row
    except Exception as exc:
        LOG.info('Legacy dbm import unavailable: %s', exc)


class LegacyStore:
    """Previous cache formats, used only if the native engine cannot be used."""

    def __init__(self, dbm_path, json_path):
        self.json_path = json_path
        self.backend = 'json'
        self._db = None
        self._data = _read_json(json_path)
        self._changed = set()
        self._removed = set()
        try:
            import dbm
            self._db = dbm.open(dbm_path, 'c')
            keys = self._db.keys()
            if keys:
                self._data = {}
                for key in keys:
                    row = _decode(self._db[key])
                    if row is not None:
                        self._data[key.decode('utf-8', 'surrogateescape')] = row
            else:
                self._changed.update(self._data)
            self.backend = 'dbm'
        except Exception as exc:
            LOG.info('dbm metadata unavailable; using JSON: %s', exc)
            try:
                self._close_db()
            except Exception:
                pass
            self._data = {**_read_json(json_path), **self._data}

    def get(self, path):
        return self._data.get(path)

    def set(self, path, row):
        self._data[path] = dict(row)
        self._changed.add(path)
        self._removed.discard(path)

    def remove(self, path):
        if path in self._data:
            del self._data[path]
            self._changed.discard(path)
            self._removed.add(path)

    def paths(self):
        return list(self._data)

    def _close_db(self):
        if self._db is not None:
            try:
                self._db.close()
            finally:
                self._db = None

    def close(self):
        try:
            if self._db is not None:
                for path in self._changed:
                    self._db[path.encode('utf-8', 'surrogateescape')] = json.dumps(
                        self._data[path], separators=(',', ':')).encode('utf-8')
                for path in self._removed:
                    key = path.encode('utf-8', 'surrogateescape')
                    if key in self._db:
                        del self._db[key]
                self._close_db()
                return
        except Exception as exc:
            LOG.info('dbm save failed; preserving cache in JSON: %s', exc)
            self.backend = 'json'
            self._changed.update(self._data)
            try:
                self._close_db()
            except Exception:
                pass
        if self._changed or self._removed:
            try:
                with open(self.json_path + '.tmp', 'w', encoding='utf-8') as target:
                    json.dump(self._data, target, separators=(',', ':'))
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(self.json_path + '.tmp', self.json_path)
            except OSError as exc:
                LOG.info('JSON metadata save failed: %s', exc)


class SQLiteStore:
    backend = 'sqlite'

    def __init__(self, path, dbm_path, json_path):
        # Import lazily so older Python runtimes without ctypes still fall back.
        from native_sqlite import Connection
        self._connection = Connection(path)
        self._writing = False
        try:
            # A short-lived rollback journal works on the SD-card filesystems
            # used by KNULLI, without WAL shared-memory files. Keep durable sync.
            self._connection.execute('PRAGMA journal_mode=DELETE')
            self._connection.execute('PRAGMA synchronous=FULL')
            self._connection.execute('PRAGMA cache_size=-2048')
            version = self._connection.execute('PRAGMA user_version')[0][0]
            if version == 0:
                self._begin()
                self._connection.execute('''CREATE TABLE IF NOT EXISTS metadata (
                    path BLOB PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL,
                    album TEXT NOT NULL, mtime REAL NOT NULL, size INTEGER NOT NULL
                ) WITHOUT ROWID''')
                for legacy_path, row in _legacy_rows(dbm_path, json_path):
                    self.set(legacy_path, row)
                # Schema + import marker + data commit together. An interrupted
                # first launch retries the entire import on the next launch.
                self._connection.execute('PRAGMA user_version=1')
                self._commit()
            elif version != 1:
                raise RuntimeError('Unsupported Walkman database version: %d' % version)
            self._connection.execute('SELECT path, title, artist, album, mtime, size FROM metadata LIMIT 0')
            LOG.info('metadata database: bundled SQLite %s', self._connection.version)
        except Exception:
            self._connection.close()
            raise

    @staticmethod
    def _key(path):
        # Byte keys also preserve POSIX filenames containing non-UTF-8 bytes.
        return path.encode('utf-8', 'surrogateescape')

    def _begin(self):
        if not self._writing:
            self._connection.execute('BEGIN IMMEDIATE')
            self._writing = True

    def _commit(self):
        if self._writing:
            self._connection.execute('COMMIT')
            self._writing = False

    def get(self, path):
        rows = self._connection.execute(
            'SELECT title, artist, album, mtime, size FROM metadata WHERE path=?', (self._key(path),))
        return dict(zip(FIELDS, rows[0])) if rows else None

    def set(self, path, row):
        self._begin()
        # Invalid legacy file stamps force a rescan, instead of aborting migration.
        mtime, size = row.get('mtime', -1), row.get('size', -1)
        if not isinstance(mtime, (int, float)) or not math.isfinite(mtime):
            mtime = -1
        if not isinstance(size, int) or not -(2 ** 63) <= size < 2 ** 63:
            size = -1
        self._connection.execute('''INSERT INTO metadata(path,title,artist,album,mtime,size)
            VALUES(?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
            title=excluded.title, artist=excluded.artist, album=excluded.album,
            mtime=excluded.mtime, size=excluded.size''',
            (self._key(path), str(row.get('title') or ''), str(row.get('artist') or ''),
             str(row.get('album') or ''), mtime, size))

    def remove(self, path):
        self._begin()
        self._connection.execute('DELETE FROM metadata WHERE path=?', (self._key(path),))

    def paths(self):
        return [row[0].decode('utf-8', 'surrogateescape') for row in
                self._connection.execute('SELECT path FROM metadata')]

    def close(self, commit=True):
        try:
            if commit:
                self._commit()
        finally:
            self._connection.close()


class MetadataStore:
    """One interface: bundled SQLite first, then dbm, then JSON."""

    def __init__(self, dbm_path, json_path):
        self.dbm_path, self.json_path = dbm_path, json_path
        self.sqlite_path = os.path.join(os.path.dirname(dbm_path), 'library.sqlite3')
        self._pending = {}
        self._removed = set()
        self._closed = False
        self.error = None
        try:
            self._store = SQLiteStore(self.sqlite_path, dbm_path, json_path)
        except Exception as exc:
            self.error = str(exc)
            LOG.info('Bundled SQLite unavailable; using legacy cache: %s', exc)
            self._store = LegacyStore(dbm_path, json_path)

    @property
    def backend(self):
        return self._store.backend

    def _fallback(self, exc):
        self.error = str(exc)
        LOG.info('SQLite cache operation failed; using legacy cache: %s', exc)
        try:
            self._store.close(commit=False)
        except Exception:
            pass
        self._store = LegacyStore(self.dbm_path, self.json_path)
        # Preserve every successful write/deletion from the current scan even
        # when the SQLite failure happens during the final commit.
        for path, row in self._pending.items():
            self._store.set(path, row)
        for path in self._removed:
            self._store.remove(path)

    def _call(self, method, *args):
        if self._closed:
            raise RuntimeError('Metadata cache is closed')
        try:
            return getattr(self._store, method)(*args)
        except Exception as exc:
            if self.backend != 'sqlite':
                raise
            self._fallback(exc)
            return getattr(self._store, method)(*args)

    def get(self, path):
        return self._call('get', path)

    def set(self, path, row):
        self._pending[path] = dict(row)
        self._removed.discard(path)
        self._call('set', path, row)

    def remove(self, path):
        self._pending.pop(path, None)
        self._removed.add(path)
        self._call('remove', path)

    def paths(self):
        return self._call('paths')

    def close(self):
        if not self._closed:
            self._call('close')
            self._closed = True
            self._pending.clear()
            self._removed.clear()

    @staticmethod
    def cache_files(dbm_path, json_path):
        sql = os.path.join(os.path.dirname(dbm_path), 'library.sqlite3')
        return [json_path, json_path + '.tmp', dbm_path, dbm_path + '.db',
                dbm_path + '.dat', dbm_path + '.dir', dbm_path + '.bak',
                sql, sql + '-journal', sql + '-wal', sql + '-shm']

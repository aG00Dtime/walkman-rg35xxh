"""Run on KNULLI, or set WALKMAN_SQLITE_TEST_LIBRARY to a host test build."""
import dbm.dumb
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metadata_store
import native_sqlite

TEST_LIBRARY = os.environ.get('WALKMAN_SQLITE_TEST_LIBRARY')
NATIVE = bool(TEST_LIBRARY) or (platform.system() == 'Linux' and platform.machine() in ('aarch64', 'arm64'))
ROW = {'title': 'HEAVEN AND BACK', 'artist': 'Chase Atlantic', 'album': 'Phases',
       'mtime': 1789232451.123, 'size': 10096713}
TRACK = '/music/[2019] Phases/07 - HEAVEN AND BACK.mp3'


class StorageFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='walkman-db-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dbm = str(self.root / 'library.db')
        self.json = str(self.root / 'metadata.json')
        self.sql = str(self.root / 'library.sqlite3')

    def open_store(self):
        store = metadata_store.MetadataStore(self.dbm, self.json)
        self.addCleanup(store.close)
        return store


class FallbackTests(StorageFixture):
    def test_missing_engine_uses_dbm_and_survives_reopen(self):
        with patch('metadata_store.SQLiteStore', side_effect=OSError('missing engine')):
            store = self.open_store()
            self.assertEqual(store.backend, 'dbm')
            store.set(TRACK, ROW)
            store.close()
            self.assertEqual(self.open_store().get(TRACK), ROW)

    def test_no_engine_or_dbm_uses_json(self):
        with patch('metadata_store.SQLiteStore', side_effect=ImportError('no ctypes')), patch('dbm.open', side_effect=OSError('no dbm')):
            store = self.open_store()
            self.assertEqual(store.backend, 'json')
            store.set(TRACK, ROW)
            store.close()
            self.assertEqual(json.loads(Path(self.json).read_text())[TRACK], ROW)
            self.assertEqual(self.open_store().get(TRACK), ROW)


@unittest.skipUnless(NATIVE, 'native tests require KNULLI or WALKMAN_SQLITE_TEST_LIBRARY')
class NativeTests(StorageFixture):
    def setUp(self):
        super().setUp()
        if TEST_LIBRARY:
            override = patch('native_sqlite.bundled_library', return_value=Path(TEST_LIBRARY))
            override.start()
            self.addCleanup(override.stop)

    def connection(self, path=None):
        connection = native_sqlite.Connection(path or self.sql)
        self.addCleanup(connection.close)
        return connection

    def test_native_engine_without_python_sqlite_module(self):
        with patch.dict(sys.modules, {'sqlite3': None, '_sqlite3': None}):
            store = self.open_store()
            self.assertEqual(store.backend, 'sqlite', store.error)
            store.set(TRACK, ROW)
            store.close()
            self.assertEqual(self.open_store().get(TRACK), ROW)
        self.assertEqual(Path(self.sql).read_bytes()[:16], b'SQLite format 3\0')
        self.assertEqual(self.connection().execute('PRAGMA integrity_check'), [('ok',)])

    def test_bound_values_blobs_unicode_null_and_statement_reuse(self):
        connection = self.connection()
        for values in [(None, '', b''), (2 ** 60, -12.75, b'\x00\xff\x00'),
                       ("O'Brien; DROP TABLE metadata; --", 'Beyoncé 🎵\x00end', -2 ** 60)]:
            self.assertEqual(connection.execute('SELECT ?, ?, ?', values), [values])
        with self.assertRaises(native_sqlite.SQLiteError):
            connection.execute('SELECT ?, ?, ?', (1,))
        self.assertEqual(connection.execute('SELECT ?, ?, ?', (1, 2, 3)), [(1, 2, 3)])
        with self.assertRaises(native_sqlite.SQLiteError):
            connection.execute('SELECT 1; SELECT 2')

    def test_migration_keeps_originals_and_does_not_reimport_deleted_rows(self):
        Path(self.json).write_text(json.dumps({TRACK: dict(ROW, title='old JSON title'), '/json-only.mp3': ROW}))
        with dbm.dumb.open(self.dbm, 'c') as old:
            old[TRACK.encode()] = json.dumps(ROW).encode()
            old[b'/bad-row.mp3'] = b'broken json'
        originals = {path: hashlib.sha256(path.read_bytes()).digest() for path in self.root.iterdir()}
        store = self.open_store()
        self.assertEqual(store.backend, 'sqlite', store.error)
        self.assertEqual(store.get(TRACK), ROW)
        self.assertEqual(store.get('/json-only.mp3'), ROW)
        self.assertEqual(len(store.paths()), 2)
        store.remove(TRACK)
        store.close()
        self.assertIsNone(self.open_store().get(TRACK))
        for path, digest in originals.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest)

    def test_non_utf8_filename_round_trip(self):
        path = '/music/raw-\udcff.mp3'
        store = self.open_store()
        store.set(path, ROW)
        store.close()
        reopened = self.open_store()
        self.assertEqual(reopened.get(path), ROW)
        self.assertIn(path, reopened.paths())

    def test_interrupted_import_rolls_back_and_retries(self):
        Path(self.json).write_text(json.dumps({TRACK: ROW}))
        with patch.object(metadata_store.SQLiteStore, '_commit', side_effect=OSError('interrupted import')):
            with self.assertRaises(OSError):
                metadata_store.SQLiteStore(self.sql, self.dbm, self.json)
        with self.connection() as connection:
            self.assertEqual(connection.execute('PRAGMA user_version'), [(0,)])
        self.assertEqual(self.open_store().get(TRACK), ROW)

    def test_bulk_scan_commit_update_and_delete(self):
        store = self.open_store()
        self.assertEqual(store.backend, 'sqlite', store.error)
        for index in range(10000):
            store.set('/music/%d.mp3' % index, dict(ROW, size=index))
        store.close()
        reopened = self.open_store()
        self.assertEqual(len(reopened.paths()), 10000)
        self.assertEqual(reopened.get('/music/9999.mp3')['size'], 9999)
        reopened.set('/music/5.mp3', dict(ROW, title='Changed'))
        reopened.remove('/music/6.mp3')
        reopened.close()
        final = self.open_store()
        self.assertEqual(len(final.paths()), 9999)
        self.assertEqual(final.get('/music/5.mp3')['title'], 'Changed')
        self.assertIsNone(final.get('/music/6.mp3'))

    def test_commit_failure_preserves_pending_changes_in_fallback(self):
        store = self.open_store()
        self.assertEqual(store.backend, 'sqlite', store.error)
        store.set(TRACK, ROW)
        with patch.object(store._store, '_commit', side_effect=OSError('disk write error')):
            store.close()
        self.assertIn(store.backend, ('dbm', 'json'))
        with patch('metadata_store.SQLiteStore', side_effect=OSError('unavailable')):
            self.assertEqual(self.open_store().get(TRACK), ROW)

    def test_corrupt_database_is_preserved_and_falls_back(self):
        corrupt = b'broken database contents' * 200
        Path(self.sql).write_bytes(corrupt)
        store = self.open_store()
        self.assertIn(store.backend, ('dbm', 'json'))
        store.set(TRACK, ROW)
        store.close()
        self.assertEqual(Path(self.sql).read_bytes(), corrupt)

    def test_uncommitted_process_exit_recovers_last_commit(self):
        store = self.open_store()
        store.set(TRACK, ROW)
        store.close()
        code = '''import os, sys
from native_sqlite import Connection
connection = Connection(sys.argv[1], library_path=sys.argv[2])
connection.execute('BEGIN IMMEDIATE')
connection.execute('DELETE FROM metadata')
os._exit(0)
'''
        library = str(TEST_LIBRARY or native_sqlite.bundled_library())
        subprocess.run([sys.executable, '-c', code, self.sql, library], check=True,
                       cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(self.open_store().get(TRACK), ROW)
        self.assertEqual(self.connection().execute('PRAGMA integrity_check'), [('ok',)])

    def test_busy_database_fails_cleanly_and_can_retry(self):
        store = self.open_store()
        store.close()
        with self.connection() as writer:
            writer.execute('BEGIN IMMEDIATE')
            with native_sqlite.Connection(self.sql, library_path=TEST_LIBRARY, timeout_ms=10) as other:
                with self.assertRaises(native_sqlite.SQLiteError):
                    other.execute('BEGIN IMMEDIATE')
                writer.execute('ROLLBACK')
                other.execute('BEGIN IMMEDIATE')
                other.execute('ROLLBACK')

    def test_read_failure_falls_back_without_losing_current_scan_writes(self):
        store = self.open_store()
        self.assertEqual(store.backend, 'sqlite', store.error)
        store.set(TRACK, ROW)
        with patch.object(store._store, 'get', side_effect=OSError('read error')):
            self.assertEqual(store.get(TRACK), ROW)
        self.assertIn(store.backend, ('dbm', 'json'))


if __name__ == '__main__':
    unittest.main()

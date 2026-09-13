"""Small SQLite C-API adapter. Uses Walkman's bundled engine, not Python sqlite3."""
import ctypes as C
import os
import platform
import threading
from pathlib import Path


class SQLiteError(RuntimeError):
    pass


def bundled_library():
    if platform.system() != 'Linux' or platform.machine().lower() not in ('aarch64', 'arm64'):
        raise SQLiteError('The bundled SQLite engine targets Linux ARM64')
    return Path(__file__).resolve().parent / 'native/linux-aarch64/libwalkman_sqlite3.so'


class Connection:
    """Bound parameters and transactions for Walkman's internal SQL only.

    Results are fully materialized before a statement is reset. The connection
    serializes calls and owns every prepared statement until close().
    `library_path` is an explicit override for maintainer tests, never discovery
    of an arbitrary system SQLite library on the handheld.
    """

    def __init__(self, path, *, library_path=None, timeout_ms=1500):
        self.library_path = str(library_path if library_path is not None else bundled_library())
        self._lib = C.CDLL(self.library_path)
        self._lock = threading.RLock()
        self._db = C.c_void_p()
        self._statements = {}
        self._bind_api()
        self.version = self._lib.sqlite3_libversion().decode('ascii')
        # READWRITE | CREATE | FULLMUTEX. No extension loading or URI filenames.
        result = self._lib.sqlite3_open_v2(os.fsencode(path), C.byref(self._db), 0x10006, None)
        if result != 0:
            error = self._error(result)
            self.close()
            raise error
        self._check(self._lib.sqlite3_busy_timeout(self._db, timeout_ms))

    def _bind_api(self):
        ptr, integer = C.c_void_p, C.c_int
        signatures = {
            'libversion': (C.c_char_p, []),
            'open_v2': (integer, [C.c_char_p, C.POINTER(ptr), integer, C.c_char_p]),
            'close_v2': (integer, [ptr]),
            'errmsg': (C.c_char_p, [ptr]),
            'busy_timeout': (integer, [ptr, integer]),
            'prepare_v2': (integer, [ptr, C.c_char_p, integer, C.POINTER(ptr), C.POINTER(C.c_char_p)]),
            'bind_parameter_count': (integer, [ptr]),
            'bind_null': (integer, [ptr, integer]),
            'bind_int64': (integer, [ptr, integer, C.c_int64]),
            'bind_double': (integer, [ptr, integer, C.c_double]),
            'bind_text': (integer, [ptr, integer, C.c_char_p, integer, ptr]),
            'bind_blob': (integer, [ptr, integer, C.c_char_p, integer, ptr]),
            'step': (integer, [ptr]),
            'reset': (integer, [ptr]),
            'clear_bindings': (integer, [ptr]),
            'finalize': (integer, [ptr]),
            'column_count': (integer, [ptr]),
            'column_type': (integer, [ptr, integer]),
            'column_int64': (C.c_int64, [ptr, integer]),
            'column_double': (C.c_double, [ptr, integer]),
            'column_text': (ptr, [ptr, integer]),
            'column_blob': (ptr, [ptr, integer]),
            'column_bytes': (integer, [ptr, integer]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self._lib, 'sqlite3_' + name)
            function.restype, function.argtypes = result, args

    def _error(self, code):
        message = self._lib.sqlite3_errmsg(self._db) if self._db else b'Cannot open SQLite database'
        return SQLiteError('SQLite %d: %s' % (code, message.decode('utf-8', 'replace')))

    def _check(self, result):
        if result != 0:
            raise self._error(result)

    def execute(self, sql, parameters=()):
        with self._lock:
            if not self._db:
                raise SQLiteError('Connection is closed')
            statement = self._statements.get(sql)
            if statement is None:
                statement = C.c_void_p()
                tail = C.c_char_p()
                encoded_sql = sql.encode('utf-8')
                self._check(self._lib.sqlite3_prepare_v2(
                    self._db, encoded_sql, -1, C.byref(statement), C.byref(tail)))
                if not statement or (tail.value and tail.value.strip()):
                    if statement:
                        self._lib.sqlite3_finalize(statement)
                    raise SQLiteError('Exactly one SQL statement is required')
                # Walkman uses a fixed set of queries; bound the cache for tests/tools too.
                if len(self._statements) >= 32:
                    self._lib.sqlite3_finalize(self._statements.pop(next(iter(self._statements))))
                self._statements[sql] = statement
            try:
                if len(parameters) != self._lib.sqlite3_bind_parameter_count(statement):
                    raise SQLiteError('Incorrect SQL parameter count')
                for index, value in enumerate(parameters, 1):
                    if value is None:
                        result = self._lib.sqlite3_bind_null(statement, index)
                    elif isinstance(value, int):
                        if not -(2 ** 63) <= value < 2 ** 63:
                            raise OverflowError('SQLite integers are signed 64-bit values')
                        result = self._lib.sqlite3_bind_int64(statement, index, value)
                    elif isinstance(value, float):
                        result = self._lib.sqlite3_bind_double(statement, index, value)
                    elif isinstance(value, (str, bytes)):
                        data = value.encode('utf-8') if isinstance(value, str) else value
                        bind = self._lib.sqlite3_bind_text if isinstance(value, str) else self._lib.sqlite3_bind_blob
                        # SQLITE_TRANSIENT copies the Python buffer before it is released.
                        result = bind(statement, index, data, len(data), C.c_void_p(-1))
                    else:
                        raise TypeError('Unsupported SQLite parameter type: ' + type(value).__name__)
                    self._check(result)
                rows = []
                while True:
                    result = self._lib.sqlite3_step(statement)
                    if result == 101:  # SQLITE_DONE
                        return rows
                    if result != 100:  # SQLITE_ROW
                        raise self._error(result)
                    rows.append(tuple(self._column(statement, index)
                                      for index in range(self._lib.sqlite3_column_count(statement))))
            finally:
                # reset reports the prior step error; that error was already raised above.
                self._lib.sqlite3_reset(statement)
                self._lib.sqlite3_clear_bindings(statement)

    def _column(self, statement, index):
        kind = self._lib.sqlite3_column_type(statement, index)
        if kind == 1:
            return self._lib.sqlite3_column_int64(statement, index)
        if kind == 2:
            return self._lib.sqlite3_column_double(statement, index)
        if kind == 5:
            return None
        pointer = (self._lib.sqlite3_column_text if kind == 3 else self._lib.sqlite3_column_blob)(statement, index)
        size = self._lib.sqlite3_column_bytes(statement, index)
        value = C.string_at(pointer, size) if size else b''
        return value.decode('utf-8') if kind == 3 else value

    def close(self):
        with self._lock:
            if self._db:
                for statement in self._statements.values():
                    self._lib.sqlite3_finalize(statement)
                self._statements.clear()
                self._check(self._lib.sqlite3_close_v2(self._db))
                self._db = C.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        # SQLite rolls back an uncommitted transaction when closing.
        self.close()

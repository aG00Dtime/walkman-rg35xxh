# Bundled SQLite

`linux-aarch64/libwalkman_sqlite3.so` is the real SQLite C engine, built for
Linux ARM64 with a glibc 2.17 baseline. KNULLI Scarab on the RG35XX H supplies
glibc 2.40 and Python's `ctypes`, which loads this library by its absolute
path inside Walkman. The Python `sqlite3`/`_sqlite3` modules are not needed.
Nothing is installed or downloaded on the handheld. The engine runs inside
the player process; there is no database server or per-query shell process.

The supported release includes this binary and its build manifest. It does
not search for a system SQLite library. Other architectures fall back to
dbm/JSON unless a matching engine is added in a future release.

## Rebuilding (maintainers only)

Install [Zig 0.15.2](https://ziglang.org/download/) on a development computer,
then run from the repository root:

```sh
python tools/build_sqlite.py --zig /path/to/zig
python tools/verify_native.py
```

The script downloads a pinned official SQLite release, verifies its SHA3-256
checksum, compiles it, and records the binary SHA-256 in `build.json`.
The source and toolchain are build-time downloads only. Do not replace the
library with an Android, x86, or Python-version-specific binary.

For host tests on Linux x86-64:

```sh
python tools/build_sqlite.py --zig /path/to/zig --target x86_64-linux-gnu.2.17 --output /tmp/walkman-sqlite-host/libwalkman_sqlite3.so
WALKMAN_SQLITE_TEST_LIBRARY=/tmp/walkman-sqlite-host/libwalkman_sqlite3.so python -m unittest discover -s tests
```

The test variable is used by tests only. Production code always selects the
bundled ARM64 library. On the RG35XX H, the same tests run without an override.

## Storage behavior

- `.cache/metadata/library.sqlite3` contains track paths, titles, artists,
  albums, file modification times, and sizes. Paths are indexed byte keys.
- Existing dbm and JSON metadata is imported once in an atomic transaction.
  Existing files are retained; the import marker commits with the data.
- Unchanged scans read the cache. Changed rows are saved together at the end
  of a scan, using bound parameters and reusable prepared statements.
- DELETE journaling and FULL synchronization keep SQLite's normal recovery
  protections enabled on the device's SD-card filesystem. No WAL mode or
  unsafe `synchronous=OFF` setting is used.
- If the engine cannot load, or database access fails, the app uses dbm and
  then JSON. The log records the reason and Settings shows the active backend.
  The current scan's pending cache writes are preserved on a fallback.
- Clearing metadata in Settings removes SQLite and legacy metadata caches.
  Music, state, artwork, and visualizer files are independent.

The adapter is deliberately limited to Walkman's internal storage needs. It
does not implement Python's full DB-API. Database migration changes storage;
it does not replace filesystem scans or move artwork/viz bytes into SQL.

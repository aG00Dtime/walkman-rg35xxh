#!/usr/bin/env python3
"""Maintainer tool: build the bundled C library; never run on the handheld."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile

VERSION = '3.53.4'
SOURCE_URL = 'https://sqlite.org/2026/sqlite-amalgamation-3530400.zip'
SOURCE_SHA3 = '628a44cfe82c66aed1ccbbe85a562d2e33ebe64b3288981ed76285612227934e'
TARGET = 'aarch64-linux-gnu.2.17'
FLAGS = [
    '-O2', '-shared', '-fPIC', '-s',
    '-DSQLITE_THREADSAFE=1', '-DSQLITE_DEFAULT_MEMSTATUS=0',
    '-DSQLITE_OMIT_LOAD_EXTENSION', '-DSQLITE_DQS=0', '-DSQLITE_TEMP_STORE=3',
]
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig', default='zig', help='Zig 0.15.2 executable')
    parser.add_argument('--target', default=TARGET, help='Override only for development tests')
    parser.add_argument('--output', type=Path, default=ROOT / 'native/linux-aarch64/libwalkman_sqlite3.so')
    args = parser.parse_args()
    compiler_version = subprocess.check_output([args.zig, 'version'], text=True).strip()
    if compiler_version != '0.15.2':
        raise SystemExit('Use Zig 0.15.2 to reproduce the bundled build.')
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
        source = response.read()
    if hashlib.sha3_256(source).hexdigest() != SOURCE_SHA3:
        raise SystemExit('SQLite source checksum mismatch; no build performed.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    link_flags = [] if 'windows' in args.target else ['-Wl,-Bsymbolic', '-lpthread', '-lm']
    with tempfile.TemporaryDirectory(prefix='walkman-sqlite-build-') as directory:
        build = Path(directory)
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            (build / 'sqlite3.c').write_bytes(archive.read('sqlite-amalgamation-3530400/sqlite3.c'))
        temporary_output = build / args.output.name
        subprocess.run([
            args.zig, 'cc', '-target', args.target, *FLAGS, 'sqlite3.c',
            *link_flags, '-o', str(temporary_output),
        ], cwd=build, check=True)
        binary = temporary_output.read_bytes()
        args.output.write_bytes(binary)
    manifest = {
        'sqlite_version': VERSION, 'source_url': SOURCE_URL,
        'source_sha3_256': SOURCE_SHA3, 'compiler': 'Zig ' + compiler_version,
        'target': args.target, 'flags': FLAGS + link_flags,
        'library': args.output.name, 'sha256': hashlib.sha256(binary).hexdigest(),
        'size_bytes': len(binary),
    }
    args.output.with_name('build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Built SQLite %s for %s (%d bytes)' % (VERSION, args.target, len(binary)))


if __name__ == '__main__':
    main()

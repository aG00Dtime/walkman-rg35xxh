#!/usr/bin/env python3
"""Fail packaging if the supported ARM64 engine is absent or incorrect."""
import hashlib
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]


def verify():
    directory = ROOT / 'native/linux-aarch64'
    manifest = json.loads((directory / 'build.json').read_text(encoding='utf-8'))
    binary = (directory / 'libwalkman_sqlite3.so').read_bytes()
    assert binary[:6] == b'\x7fELF\x02\x01', 'Expected a 64-bit little-endian ELF library'
    assert struct.unpack_from('<H', binary, 18)[0] == 183, 'Expected AArch64 machine code'
    assert hashlib.sha256(binary).hexdigest() == manifest['sha256'], 'Native library checksum mismatch'
    assert len(binary) == manifest['size_bytes'], 'Native library size mismatch'
    assert manifest['target'] == 'aarch64-linux-gnu.2.17', 'Wrong release target'
    versions = {tuple(map(int, match.split(b'.'))) for match in re.findall(rb'GLIBC_([0-9.]+)', binary)}
    assert versions and max(versions) <= (2, 17), 'Library requires a newer glibc than its build target'
    # Resolve DT_NEEDED names from ELF64 program headers, without a host readelf.
    offset = struct.unpack_from('<Q', binary, 32)[0]
    size, count = struct.unpack_from('<HH', binary, 54)
    headers = [struct.unpack_from('<IIQQQQQQ', binary, offset + size * index) for index in range(count)]
    dynamic = next(header for header in headers if header[0] == 2)
    entries = [struct.unpack_from('<qQ', binary, index)
               for index in range(dynamic[2], dynamic[2] + dynamic[5], 16)]
    strings_va = next(value for tag, value in entries if tag == 5)
    segment = next(header for header in headers if header[0] == 1 and header[3] <= strings_va < header[3] + header[5])
    strings = segment[2] + strings_va - segment[3]
    needed = []
    for tag, value in entries:
        if tag == 1:
            start = strings + value
            needed.append(binary[start:binary.index(b'\0', start)].decode('ascii'))
    assert set(needed) <= {'libc.so.6', 'libpthread.so.0', 'libm.so.6', 'ld-linux-aarch64.so.1'}, needed
    assert 'libc.so.6' in needed, 'Expected the system C runtime'
    print('Verified SQLite %s: ARM64, glibc <= 2.17, %.2f MiB' %
          (manifest['sqlite_version'], len(binary) / 1048576))
    print('System libraries: ' + ', '.join(needed))


if __name__ == '__main__':
    verify()

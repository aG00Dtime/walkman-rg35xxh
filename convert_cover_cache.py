#!/usr/bin/env python3
"""Convert Walkman's legacy PNG artwork cache to compact JPEG files."""
import argparse
import os
import subprocess


def valid_jpeg(path):
    try:
        with open(path, 'rb') as image:
            return image.read(3) == b'\xff\xd8\xff'
    except OSError:
        return False


def convert(source, keep_old=False):
    target = os.path.splitext(source)[0] + '.jpg'
    if valid_jpeg(target):
        if not keep_old:
            os.unlink(source)
        return 'already converted'
    temporary = target + '.tmp.jpg'
    filter_args = []
    if os.path.basename(source).startswith('artist-'):
        filter_args = ['-vf', 'scale=128:128:force_original_aspect_ratio=increase,crop=128:128']
    try:
        subprocess.run([
            'ffmpeg', '-y', '-v', 'error', '-i', source, '-frames:v', '1',
            *filter_args, '-q:v', '8', temporary,
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
           timeout=12, check=False)
        if not valid_jpeg(temporary):
            return 'failed'
        os.replace(temporary, target)
        if not keep_old:
            os.unlink(source)
        return 'converted'
    except (OSError, subprocess.SubprocessError):
        return 'failed'
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def main():
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache', 'covers')
    parser = argparse.ArgumentParser(description='Convert Walkman cover-cache PNG files to JPEG.')
    parser.add_argument('directory', nargs='?', default=default, help='cover cache folder')
    parser.add_argument('--keep-old', action='store_true', help='keep the PNG after a successful conversion')
    args = parser.parse_args()
    try:
        names = sorted(name for name in os.listdir(args.directory) if name.endswith('.png'))
    except OSError as error:
        raise SystemExit('Cannot open cache folder: %s' % error)
    results = {}
    for name in names:
        result = convert(os.path.join(args.directory, name), args.keep_old)
        results[result] = results.get(result, 0) + 1
        print('%s: %s' % (name, result))
    print('Finished: %d files; %s' % (len(names), ', '.join('%s %s' % (count, result) for result, count in sorted(results.items())) or 'nothing to convert'))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Convert Walkman's legacy .viz cache files to the compact .viz2 format."""
import argparse
import array
import math
import os


OLD_BARS = 26
OLD_FPS = 10
NEW_BARS = 20
NEW_FPS = 6
MAGIC = b'WVZ2'


def valid_v2(path):
    try:
        size = os.path.getsize(path)
        if size <= len(MAGIC) or (size - len(MAGIC)) % NEW_BARS:
            return False
        with open(path, 'rb') as cache_file:
            return cache_file.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def sample(frame, position):
    low = int(position)
    high = min(OLD_BARS - 1, low + 1)
    mix = position - low
    return frame[low] + (frame[high] - frame[low]) * mix


def convert(source, keep_old=False):
    target = source + '2'
    if valid_v2(target):
        if not keep_old:
            os.unlink(source)
        return 'already converted'

    values = array.array('f')
    try:
        with open(source, 'rb') as cache_file:
            values.fromfile(cache_file, os.path.getsize(source) // values.itemsize)
    except (OSError, EOFError):
        return 'unreadable'
    if not values or len(values) % OLD_BARS:
        return 'invalid legacy file'

    old_frames = len(values) // OLD_BARS
    new_frames = int(math.ceil(old_frames * NEW_FPS / OLD_FPS))
    temporary = target + '.tmp'
    try:
        with open(temporary, 'wb') as cache_file:
            cache_file.write(MAGIC)
            for output_frame in range(new_frames):
                source_position = output_frame * OLD_FPS / NEW_FPS
                first = min(old_frames - 1, int(source_position))
                second = min(old_frames - 1, first + 1)
                time_mix = source_position - int(source_position)
                first_frame = values[first * OLD_BARS:(first + 1) * OLD_BARS]
                second_frame = values[second * OLD_BARS:(second + 1) * OLD_BARS]
                encoded = []
                for bar in range(NEW_BARS):
                    band_position = bar * (OLD_BARS - 1) / (NEW_BARS - 1)
                    value = sample(first_frame, band_position)
                    if second != first:
                        value += (sample(second_frame, band_position) - value) * time_mix
                    value = value if math.isfinite(value) else 0.0
                    encoded.append(max(0, min(255, round(value * 255))))
                cache_file.write(bytes(encoded))
        os.replace(temporary, target)
        if not keep_old:
            os.unlink(source)
        return 'converted'
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return 'failed'


def main():
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache', 'visualizer')
    parser = argparse.ArgumentParser(description='Convert Walkman .viz files to compact .viz2 files.')
    parser.add_argument('directory', nargs='?', default=default, help='visualizer cache folder')
    parser.add_argument('--keep-old', action='store_true', help='keep legacy .viz files after conversion')
    args = parser.parse_args()

    try:
        names = sorted(name for name in os.listdir(args.directory) if name.endswith('.viz'))
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

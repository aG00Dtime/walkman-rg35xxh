#!/usr/bin/python3
"""Walkman: local music and media playback for the RG35XX H."""
import array as _array
import glob
import hashlib
import json
import logging
import math
import os
import re
import random
import select
import signal
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.request
import urllib.parse
import pygame
from design import Design, THEMES
from metadata_store import MetadataStore

try:
    import numpy as _np
except ImportError:
    _np = None

ROOT = os.path.dirname(os.path.abspath(__file__))
MUSIC = os.environ.get('WALKMAN_MUSIC', os.path.join(ROOT, 'music'))
VIDEO = os.environ.get('WALKMAN_VIDEO', os.path.join(ROOT, 'video'))
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.mpeg', '.mpg')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS + IMAGE_EXTENSIONS
LOG = logging.getLogger('walkman')


_VIZ_N     = 20
_VIZ_SR    = 8000   # decode sample rate — 8kHz mono is enough for visualization
_VIZ_WIN   = 256    # Goertzel window (longer = better freq discrimination)
_VIZ_FPS   = 6      # display smoothing keeps this looking fluid at 30 fps
_VIZ_STEP  = _VIZ_SR // _VIZ_FPS
_VIZ_CACHE_MAGIC = b'WVZ2'

# Target frequencies log-spaced from 40 Hz to 3800 Hz (covers bass → treble)
_VIZ_FREQS = [40.0 * (3800.0/40.0)**(i/(_VIZ_N-1)) for i in range(_VIZ_N)]
# Goertzel coefficient for each target frequency (precomputed once at startup)
_VIZ_COEFS = [2.0 * math.cos(2.0 * math.pi * f / _VIZ_SR) for f in _VIZ_FREQS]
SEARCH_LAYERS = (
    (list('1234567890-='), list('qwertyuiop[]'), list("asdfghjkl;'"), list('zxcvbnm,./') + [' ', '←']),
    (list('!@#$%^&*()_+'), list('QWERTYUIOP{}'), list('ASDFGHJKL:"|'), list('ZXCVBNM<>?') + [' ', '←']),
)


class App:
    categories = ['All Songs','Media','Albums','Artists','Favorites','Recent','Playlists','Settings']
    SEARCH_LAYERS = SEARCH_LAYERS

    def __init__(self, preview=False):
        self.preview = preview
        pygame.init()
        try: pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        except Exception: pass
        pygame.joystick.init()
        self.joys = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
        for joy in self.joys: joy.init()
        LOG.info('start; joysticks=%d', len(self.joys))
        self.screen = pygame.display.set_mode((640,480), 0 if preview else pygame.FULLSCREEN)
        pygame.display.set_caption('Walkman RG35XX_H')
        pygame.mouse.set_visible(False)
        self.design = Design(self.screen)
        self.running = True; self.view = 'home'; self.home_sel = 0
        self.screen_locked = False
        self._r1_down_at = None
        self._lock_anim_kind = None
        self._lock_anim_started = 0.0
        self._saved_brightness = None
        self._screen_dim_applied = False
        self._lock_drawn = False
        self.sel = 0; self.rows = []; self.heading = 'All Songs'; self.stack = []
        self._search = None
        self.current = None; self.position = 0.; self.duration = 0.; self.media_type = 'audio'
        self._video_return_view = 'home'
        self.paused = False; self.angle = 0.; self.queue = []; self.queue_index = 0
        self.proc = None; self.sock = None; self.buffer = b''; self.pending = b''; self.loaded = False
        self.socket_path = '/tmp/walkman-mpv.sock'
        self._owns_mpv = False; self._exit_keep_mpv = False; self.current_info = {}
        self._exit_notice = None
        self._volume = None; self._volume_shown_until = 0.0; self._battery = None
        self._sel_flash_t = 0.0
        self._viz_bars = [0.0] * _VIZ_N
        self._viz_phases = [random.uniform(0, math.tau) for _ in range(_VIZ_N)]
        self._viz_t = 0.0
        self._viz_data = []
        self._viz_track_id = 0
        self._picker_hue = 0.0
        self._fetch_status = None
        self._fetch_cancel = False
        self._viz_build_cancel = False
        self._lock_event_fds = []
        for event_path in sorted(glob.glob('/dev/input/event*')):
            try:
                with open('/sys/class/input/'+os.path.basename(event_path)+'/device/name', encoding='utf-8') as f:
                    if f.read().strip() == 'Anbernic RG35XX-H Controller':
                        self._lock_event_fds.append(os.open(event_path, os.O_RDONLY | os.O_NONBLOCK))
                        break
            except OSError: pass
        self._snd_nav = self._make_sound(660, 0.04, 0.15)
        self._snd_sel = self._make_sweep(300, 600, 0.06, 0.18)
        self._snd_back = self._make_sound(330, 0.04, 0.12)
        self._snd_lock = self._make_sweep(520, 180, 0.18, 0.20)
        self._snd_unlock = self._make_sweep(180, 520, 0.18, 0.20)
        self._state_path = os.path.join(ROOT, 'state.json')
        # Migrate old .covers/ → .cache/ on first run
        _old_covers = os.path.join(ROOT, '.covers')
        _cache_dir  = os.path.join(ROOT, '.cache')
        if os.path.isdir(_old_covers) and not os.path.isdir(_cache_dir):
            try: os.rename(_old_covers, _cache_dir)
            except OSError: pass
        os.makedirs(_cache_dir, exist_ok=True)
        # Keep cache types separate so scans and cleanup never mix their files.
        metadata_dir = os.path.join(_cache_dir, 'metadata')
        covers_dir = os.path.join(_cache_dir, 'covers')
        viz_dir = os.path.join(_cache_dir, 'visualizer')
        os.makedirs(metadata_dir, exist_ok=True)
        os.makedirs(covers_dir, exist_ok=True)
        os.makedirs(viz_dir, exist_ok=True)
        # Migrate old flat cache files into their organized directories.
        legacy_meta = os.path.join(_cache_dir, 'metadata.json')
        new_meta = os.path.join(metadata_dir, 'metadata.json')
        if os.path.isfile(legacy_meta) and not os.path.isfile(new_meta):
            try: os.replace(legacy_meta, new_meta)
            except OSError: pass
        try:
            for name in os.listdir(_cache_dir):
                source = os.path.join(_cache_dir, name)
                if not os.path.isfile(source): continue
                target_dir = covers_dir if name.endswith(('.png', '.jpg')) else viz_dir if name.endswith(('.viz', '.viz2')) else None
                if target_dir:
                    try: os.replace(source, os.path.join(target_dir, name))
                    except OSError: pass
        except OSError: pass
        # Migrate old metadata_cache.json → .cache/metadata/metadata.json
        _old_meta = os.path.join(ROOT, 'metadata_cache.json')
        if os.path.isfile(_old_meta) and not os.path.isfile(new_meta):
            try: os.rename(_old_meta, new_meta)
            except OSError: pass
        self._covers_dir = covers_dir
        self._cache_path = new_meta
        self._dbm_path = os.path.join(metadata_dir, 'library.db')
        self._metadata_backend = 'json'
        self._viz_dir = viz_dir
        try:
            with open(self._state_path, encoding='utf-8') as _f: self.state = json.load(_f)
        except (OSError, ValueError): self.state = {}
        self.state.setdefault('favorites', [])
        self.state.setdefault('recent', [])
        self.state.setdefault('sounds', True)
        self.state.setdefault('dynamic_viz', False)
        self._picker_hue = float(self.state.get('custom_hue', 30))
        self._apply_theme()
        self.metadata = {}; self.cover = None; self._viz_color_cover_key = None; self._viz_palette = ()
        self.group_covers = {}; self._cover_ready = {}; self._cover_queue = []; self._cover_lock = threading.Lock()
        self._video_thumbs = {}
        self._cover_thread = threading.Thread(target=self._cover_worker, daemon=True); self._cover_thread.start()
        self._vol_thread = threading.Thread(target=self._vol_worker, daemon=True); self._vol_thread.start()
        self.design.splash(); pygame.display.flip()
        self.scan(); self._try_reconnect()

    def _make_sound(self, freq=440, dur=0.05, vol=0.25):
        try:
            init = pygame.mixer.get_init()
            if not init or not init[0]: return None
            rate, _, channels = init; n = int(rate * dur)
            mono = [int(vol*32767*math.sin(2*math.pi*freq*i/rate)*max(0.0, 1.0-i/n)) for i in range(n)]
            buf = _array.array('h')
            for s in mono:
                buf.append(s)
                if channels == 2: buf.append(s)
            return pygame.mixer.Sound(buffer=buf)
        except Exception: return None

    def _make_sweep(self, f0=200, f1=600, dur=0.06, vol=0.2):
        try:
            init = pygame.mixer.get_init()
            if not init or not init[0]: return None
            rate, _, channels = init; n = int(rate * dur)
            mono = [int(vol*32767*math.sin(2*math.pi*(f0+(f1-f0)*i/n)*i/rate)*max(0.0, 1.0-i/n)) for i in range(n)]
            buf = _array.array('h')
            for s in mono:
                buf.append(s)
                if channels == 2: buf.append(s)
            return pygame.mixer.Sound(buffer=buf)
        except Exception: return None

    def _apply_theme(self):
        name = self.state.get('theme','Cassette')
        if name == 'Custom':
            self.design.set_theme(name, accent=Design._hsv_to_rgb(self._picker_hue, 0.72, 0.90))
        else:
            self.design.set_theme(name)

    @staticmethod
    def sample_viz_palette(surface):
        """Collect a small, stable palette from album art for the visualizer."""
        if surface is None:
            return ()
        try:
            # Ordinary scale works for indexed-color artwork too; smoothscale
            # rejects those surfaces on the handheld pygame build.
            sample = pygame.transform.scale(surface, (20, 20))
            buckets = {}
            for y in range(20):
                for x in range(20):
                    red, green, blue = sample.get_at((x, y))[:3]
                    high, low = max(red, green, blue), min(red, green, blue)
                    # Monochrome cover art should use the normal theme accent,
                    # not produce a nearly gray dynamic visualizer.
                    if high < 28 or high > 248 or high - low < 30:
                        continue
                    key = (red // 32, green // 32, blue // 32)
                    score = 1 + (high - low) / 255
                    weight, count, sr, sg, sb = buckets.get(key, (0.0, 0, 0, 0, 0))
                    buckets[key] = (weight + score, count + 1, sr + red, sg + green, sb + blue)
            if not buckets:
                return ()
            choices = []
            for weight, count, sr, sg, sb in sorted(buckets.values(), key=lambda row: row[0], reverse=True):
                color = (sr // count, sg // count, sb // count)
                if all(sum((color[i] - other[i]) ** 2 for i in range(3)) >= 52 ** 2 for other in choices):
                    choices.append(color)
                if len(choices) == 3:
                    break
            # Brighten without changing the hue.  Album art is often mastered
            # quite dark, which made the visualizer look muddy even when the
            # sampled colour itself was correct.
            def brighten(color):
                peak = max(color)
                if not peak:
                    return color
                scale = max(1.0, min(1.55, 215 / peak))
                return tuple(min(255, int(channel * scale)) for channel in color)

            choices = [brighten(color) for color in choices]
            if len(choices) == 1:
                red, green, blue = choices[0]
                return (
                    (red * 65 // 100, green * 65 // 100, blue * 65 // 100),
                    choices[0],
                    (min(255, red * 150 // 100), min(255, green * 150 // 100), min(255, blue * 150 // 100)),
                )
            return tuple(choices)
        except (pygame.error, ValueError):
            return ()

    @staticmethod
    def sample_viz_color(surface):
        palette = App.sample_viz_palette(surface)
        return palette[len(palette)//2] if palette else None

    def viz_palette(self):
        if not self.state.get('dynamic_viz') or self.cover is None:
            return ()
        key = (self.current, id(self.cover))
        if key != self._viz_color_cover_key:
            self._viz_color_cover_key = key
            self._viz_palette = self.sample_viz_palette(self.cover)
        return self._viz_palette

    def _update_viz(self, dt):
        self._viz_t += dt
        if getattr(self, 'media_type', 'audio') == 'video':
            return
        playing = bool(self.current and not self.paused and self.loaded)
        if not playing:
            for i in range(_VIZ_N):
                self._viz_bars[i] *= max(0.0, 1.0 - 4.0*dt)
            return
        if self._viz_data:
            frame = min(int(self.position * _VIZ_FPS), len(self._viz_data)-1)
            targets = [value / 255.0 for value in self._viz_data[max(0, frame)]]
        else:
            targets = [0.05 + 0.65*abs(math.sin(self._viz_t*(0.7+i*0.13)+self._viz_phases[i])) *
                       (0.5 + 0.5*abs(math.sin(self._viz_t*0.31+i*0.37))) for i in range(_VIZ_N)]
        for i, target in enumerate(targets):
            speed = 16.0 if target > self._viz_bars[i] else 6.0
            self._viz_bars[i] += (target - self._viz_bars[i]) * min(1.0, speed * dt)

    def _viz_cache_path(self, path):
        return os.path.join(self._viz_dir, hashlib.md5((path+':viz').encode()).hexdigest()+'.viz2')

    def _viz_cache_valid(self, path):
        try:
            size = os.path.getsize(path)
            if size <= len(_VIZ_CACHE_MAGIC) or (size - len(_VIZ_CACHE_MAGIC)) % _VIZ_N:
                return False
            with open(path, 'rb') as cache_file:
                return cache_file.read(len(_VIZ_CACHE_MAGIC)) == _VIZ_CACHE_MAGIC
        except OSError:
            return False

    @staticmethod
    def _read_exact(stream, size):
        chunks = []
        remaining = size
        while remaining:
            chunk = stream.read(remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)

    def _start_viz_analysis(self, path):
        self._viz_data = []
        self._viz_track_id += 1
        tid = self._viz_track_id
        # Load from disk cache if available — instant replay
        vpath = self._viz_cache_path(path)
        if self._viz_cache_valid(vpath):
            try:
                with open(vpath, 'rb') as vf:
                    raw = vf.read()[len(_VIZ_CACHE_MAGIC):]
                self._viz_data = [raw[i:i+_VIZ_N] for i in range(0, len(raw), _VIZ_N)]
                return
            except OSError: pass
        threading.Thread(target=self._analyze_track, args=(path, tid), daemon=True).start()

    def _analyze_track(self, path, track_id=None):
        """Stream compact visualizer frames from ffmpeg into the v2 cache."""
        batch = track_id is None
        proc = subprocess.Popen(
            ['ffmpeg','-v','quiet','-i',path,'-ac','1','-ar',str(_VIZ_SR),'-f','s16le','pipe:1'],
            stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        vpath = self._viz_cache_path(path)
        tmp_path = vpath + '.tmp'
        frame_bytes = _VIZ_WIN * 2
        skip_bytes = (_VIZ_STEP - _VIZ_WIN) * 2
        frames = [] if not batch else None
        count = 0
        canceled = False

        if _np is not None:
            npwin = _np.hanning(_VIZ_WIN)
            bin_lo = [max(1, round(freq * _VIZ_WIN / _VIZ_SR)) for freq in _VIZ_FREQS]
            bin_hi = [max(bin_lo[i] + 1, round(_VIZ_FREQS[min(i + 1, _VIZ_N - 1)] * _VIZ_WIN / _VIZ_SR)) for i in range(_VIZ_N)]

            def analyze(raw):
                mag = _np.abs(_np.fft.rfft(_np.frombuffer(raw, dtype=_np.int16).astype(_np.float32) / 32768.0 * npwin))
                values = []
                for low, high in zip(bin_lo, bin_hi):
                    value = float(_np.mean(mag[low:min(high, len(mag))])) / _VIZ_WIN
                    values.append(max(0.0, min(1.0, (20 * math.log10(max(value, 1e-9)) + 60) / 50)))
                return bytes(round(value * 255) for value in values)
        else:
            coefs = _VIZ_COEFS
            scale = 32768.0 * _VIZ_WIN

            def analyze(raw):
                samples = _array.array('h')
                samples.frombytes(raw)
                values = []
                for coef in coefs:
                    s1 = s2 = 0.0
                    for sample in samples:
                        s0 = sample + coef * s1 - s2
                        s2 = s1; s1 = s0
                    magnitude = math.sqrt(max(0.0, s1*s1 + s2*s2 - coef*s1*s2)) / scale
                    values.append(max(0.0, min(1.0, (20 * math.log10(max(magnitude, 1e-9)) + 60) / 50)))
                return bytes(round(value * 255) for value in values)

        try:
            with open(tmp_path, 'wb') as cache_file:
                cache_file.write(_VIZ_CACHE_MAGIC)
                while True:
                    if (batch and self._viz_build_cancel) or (not batch and track_id != self._viz_track_id):
                        canceled = True
                        break
                    raw = self._read_exact(proc.stdout, frame_bytes)
                    if len(raw) != frame_bytes:
                        break
                    encoded = analyze(raw)
                    cache_file.write(encoded)
                    if frames is not None:
                        frames.append(encoded)
                        self._viz_data = frames
                    count += 1
                    if count % 5 == 0:
                        time.sleep(0)
                    if skip_bytes and len(self._read_exact(proc.stdout, skip_bytes)) != skip_bytes:
                        break
        finally:
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired: proc.kill()
        complete = count and not canceled and (batch or track_id == self._viz_track_id)
        if complete:
            try:
                os.replace(tmp_path, vpath)
                legacy = os.path.splitext(vpath)[0] + '.viz'
                if os.path.isfile(legacy): os.unlink(legacy)
            except OSError: pass
        else:
            try: os.unlink(tmp_path)
            except OSError: pass

    def _play_sound(self, snd):
        if snd and self.state.get('sounds', True):
            try: snd.play()
            except Exception: pass

    def _poll_screen_lock(self):
        event_struct = struct.Struct('@llHHi')
        locked_now = False
        for fd in select.select(self._lock_event_fds, [], [], 0)[0]:
            try: data = os.read(fd, event_struct.size * 32)
            except BlockingIOError: continue
            for offset in range(0, len(data) - event_struct.size + 1, event_struct.size):
                _, _, kind, code, value = event_struct.unpack_from(data, offset)
                # Physical R1 reports BTN_Z (309) on this controller.
                if kind == 1 and code == 309 and value in (0, 1):
                    if self.view == 'search' and value == 1:
                        self.act('search')
                    else:
                        self.act('screen_lock_down' if value == 1 else 'screen_lock_up')
                    locked_now = True
                # The physical SELECT button reports BTN_TL2 (310).  Catch
                # it at the raw input layer so it cannot be mistaken for the
                # generic Pygame exit button mapping.
                elif kind == 1 and code == 310 and value == 1:
                    self.act('background')
                    locked_now = True
                # Physical START is BTN_TR (311), and always closes Walkman
                # normally (unlike SELECT, which keeps music playing).
                elif kind == 1 and code == 311 and value == 1:
                    self.act('quit')
                    locked_now = True
                # Physical L2 reports BTN_SELECT (314) and submits a search.
                elif kind == 1 and code == 314 and value == 1:
                    if self.view == 'search': self.act('search')
                # The RG35XX-H's physical R2 reports BTN_START (315).
                elif kind == 1 and code == 315 and value == 1:
                    if self.view != 'search': self.act('search')
        if self.screen_locked and self._r1_down_at and time.monotonic() - self._r1_down_at >= 0.9:
            self._unlock_screen()
            self._r1_down_at = None
            locked_now = True
        return locked_now

    def _lock_screen(self):
        if self.current and self.media_type == 'audio' and not self.screen_locked:
            self.screen_locked = True
            self._lock_anim_kind = 'lock'; self._lock_anim_started = time.monotonic()
            self._screen_dim_applied = False
            self._lock_drawn = False
            self._play_sound(self._snd_lock)

    def _unlock_screen(self):
        if self.screen_locked:
            self.screen_locked = False
            self._lock_anim_kind = 'unlock'; self._lock_anim_started = time.monotonic()
            self._restore_brightness()
            self._lock_drawn = False
            self._play_sound(self._snd_unlock)

    def _read_brightness(self):
        """Return current brightness as a percentage (0-100), or None."""
        try:
            r = subprocess.run(['knulli-brightness'], capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                return int(r.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return None

    def _set_brightness(self, pct):
        """Set brightness to pct (0-100). Returns True on success."""
        try:
            r = subprocess.run(['knulli-brightness', str(int(pct))],
                               capture_output=True, timeout=2)
            if r.returncode == 0:
                return True
            LOG.warning('knulli-brightness %d failed: %s', pct, r.stderr.decode().strip())
        except (OSError, subprocess.SubprocessError) as exc:
            LOG.warning('knulli-brightness unavailable: %s', exc)
        return False

    def _apply_lock_dim(self):
        dim_map = {'Off': None, 'Low': 30, 'Medium': 15, 'Dark': 5}
        pct = dim_map.get(self.state.get('lock_dim', 'Medium'))
        self._screen_dim_applied = True
        if pct is None:
            return
        cur = self._read_brightness()
        LOG.info('lock dim: %s%% -> %s%%', cur, pct)
        if cur is not None:
            self._saved_brightness = cur
        self._set_brightness(pct)

    def _restore_brightness(self):
        if self._saved_brightness is not None:
            LOG.info('restore brightness: %d%%', self._saved_brightness)
            self._set_brightness(self._saved_brightness)
            self._saved_brightness = None
        self._screen_dim_applied = False

    def _mb_search(self, artist, album):
        q = urllib.parse.quote(f'artist:"{artist}" release:"{album}"')
        url = f'https://musicbrainz.org/ws/2/release/?query={q}&limit=3&fmt=json'
        req = urllib.request.Request(url, headers={'User-Agent': 'Walkman/1.0 (rg35xxh)'})
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                releases = json.loads(r.read()).get('releases', [])
            return releases[0]['id'] if releases else None
        except Exception: return None

    def _fetch_art_worker(self, mode):
        seen = {}  # (artist_lower, album_lower) -> cover path or None
        last_req = 0.0
        tracks = list(self.tracks)
        for idx, path in enumerate(tracks):
            if self._fetch_cancel: break
            self._fetch_status = f'Checking art: {os.path.basename(path)[:34]}\n{idx+1} of {len(tracks)}'
            h = hashlib.md5((path+':64').encode()).hexdigest()
            cached = self._cover_cache_path(h)
            if mode == 'missing' and os.path.isfile(cached): continue
            meta = self.metadata.get(path, {})
            artist = meta.get('artist', '').strip()
            album  = meta.get('album',  '').strip()
            if not artist or not album: continue
            key = (artist.lower(), album.lower())
            if key in seen:
                src = seen[key]
                if src and not os.path.isfile(cached):
                    try:
                        import shutil; shutil.copy2(src, cached)
                    except OSError: pass
                continue
            self._fetch_status = f'Fetching: {os.path.basename(path)[:34]}\n{idx+1} of {len(tracks)}'
            gap = time.monotonic() - last_req
            if gap < 1.1: time.sleep(1.1 - gap)
            last_req = time.monotonic()
            mbid = self._mb_search(artist, album)
            if not mbid: seen[key] = None; continue
            gap = time.monotonic() - last_req
            if gap < 1.1: time.sleep(1.1 - gap)
            last_req = time.monotonic()
            try:
                cover_url = f'https://coverartarchive.org/release/{mbid}/front-250'
                req = urllib.request.Request(cover_url, headers={'User-Agent': 'Walkman/1.0 (rg35xxh)'})
                with urllib.request.urlopen(req, timeout=8) as r:
                    img_data = r.read()
            except Exception: seen[key] = None; continue
            tmp_raw = '/tmp/walkman_mb.jpg'
            try:
                with open(tmp_raw, 'wb') as f: f.write(img_data)
                subprocess.run(['ffmpeg','-y','-v','error','-i',tmp_raw,
                               '-vf','scale=64:64:force_original_aspect_ratio=increase,crop=64:64',
                               '-q:v','8',
                               cached],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=5)
                seen[key] = cached if os.path.isfile(cached) else None
            except Exception: seen[key] = None
        self._fetch_status = None

    def _artist_cache_path(self, artist):
        """Return the one local thumbnail path shared by an artist's albums."""
        digest = hashlib.md5((artist.casefold() + ':artist:200').encode('utf-8')).hexdigest()
        return self._cover_cache_path('artist-' + digest)

    def _fetch_artist_art_worker(self, mode):
        """Fetch optional artist photos from TheAudioDB and save them locally."""
        artists = sorted({
            (self.metadata.get(path, {}).get('artist') or '').strip()
            for path in self.tracks
        }, key=str.casefold)
        artists = [artist for artist in artists if artist]
        last_request = 0.0
        completed = 0
        try:
            for index, artist in enumerate(artists):
                if self._fetch_cancel:
                    break
                cached = self._artist_cache_path(artist)
                self._fetch_status = 'Artist photos: ' + artist[:34] + '\n%d of %d' % (index + 1, len(artists))
                if mode == 'missing' and os.path.isfile(cached):
                    completed += 1
                    continue
                # Free accounts allow 30 requests per minute. Keep under that limit.
                wait = 2.1 - (time.monotonic() - last_request)
                if wait > 0:
                    time.sleep(wait)
                last_request = time.monotonic()
                try:
                    url = 'https://www.theaudiodb.com/api/v1/json/123/search.php?' + urllib.parse.urlencode({'s': artist})
                    request = urllib.request.Request(url, headers={'User-Agent': 'Walkman/1.0 (rg35xxh)'})
                    with urllib.request.urlopen(request, timeout=10) as response:
                        payload = json.loads(response.read().decode('utf-8'))
                    rows = payload.get('artists') or []
                    image_url = rows[0].get('strArtistThumb') if rows else None
                    if not image_url:
                        completed += 1
                        continue
                    image_request = urllib.request.Request(image_url, headers={'User-Agent': 'Walkman/1.0 (rg35xxh)'})
                    with urllib.request.urlopen(image_request, timeout=12) as response:
                        image_data = response.read()
                except Exception:
                    completed += 1
                    continue
                raw = '/tmp/walkman-artist-%d.img' % threading.get_ident()
                try:
                    with open(raw, 'wb') as image_file:
                        image_file.write(image_data)
                    subprocess.run([
                        'ffmpeg', '-y', '-v', 'error', '-i', raw,
                        '-vf', 'scale=128:128:force_original_aspect_ratio=increase,crop=128:128',
                        '-q:v', '8',
                        cached,
                    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
                    if os.path.isfile(cached):
                        with self._cover_lock:
                            self._cover_ready[('Artists', artist)] = cached
                except (OSError, subprocess.SubprocessError):
                    pass
                finally:
                    try: os.unlink(raw)
                    except OSError: pass
                completed += 1
        finally:
            result = 'Artist photos canceled' if self._fetch_cancel else 'Artist photos ready'
            self._fetch_status = result + '\n%d/%d artists checked' % (completed, len(artists))
            time.sleep(1.5)
            self._fetch_status = None

    def scan(self):
        self.tracks = []; self.media = []; self.playlists = []
        os.makedirs(MUSIC, exist_ok=True)
        os.makedirs(VIDEO, exist_ok=True)
        cache = MetadataStore(self._dbm_path, self._cache_path)
        self._metadata_backend = cache.backend
        try: from mutagen import File
        except ImportError: File = None
        found = set()
        try:
            for base, _, files in os.walk(MUSIC):
                for filename in files:
                    path = os.path.join(base, filename); ext = os.path.splitext(filename)[1].lower()
                    if ext in ('.m3u', '.m3u8'): self.playlists.append(path); continue
                    if ext not in ('.mp3', '.flac', '.ogg', '.wav', '.m4a'): continue
                    self.tracks.append(path); found.add(path)
                    try: st = os.stat(path); mtime = st.st_mtime; size = st.st_size
                    except OSError: mtime = 0.0; size = 0
                    row = cache.get(path)
                    if row and abs(row.get('mtime', -1) - mtime) < 0.001 and row.get('size') == size:
                        self.metadata[path] = {'title': row.get('title',''), 'artist': row.get('artist',''), 'album': row.get('album','')}
                        continue
                    meta = {}
                    if File:
                        try:
                            tags = File(path, easy=True)
                            if tags: meta = {k: str(tags.get(k, [''])[0]) for k in ('title','artist','album')}
                        except Exception: pass
                    else:
                        try:
                            result = subprocess.run(['ffprobe','-v','error','-show_entries','format_tags=title,artist,album','-of','json',path],capture_output=True,timeout=3,check=True)
                            tags = json.loads(result.stdout).get('format',{}).get('tags',{})
                            meta = {k.lower(): str(v) for k,v in tags.items()}
                        except (OSError, ValueError, subprocess.SubprocessError): pass
                    self.metadata[path] = meta
                    cache.set(path, {'title': meta.get('title',''), 'artist': meta.get('artist',''), 'album': meta.get('album',''), 'mtime': mtime, 'size': size})
            for path in cache.paths():
                if path not in found: cache.remove(path)
        finally:
            cache.close()
            self._metadata_backend = cache.backend
        self.tracks.sort(key=lambda p: self.track_title(p).casefold())
        for base, _, files in os.walk(VIDEO):
            for filename in files:
                if os.path.splitext(filename)[1].lower() in MEDIA_EXTENSIONS:
                    self.media.append(os.path.join(base, filename))
        self.media.sort(key=lambda p: os.path.basename(p).casefold())

    def _read_volume(self):
        for mixer in ('Master','PCM','Headphone','Speaker'):
            try:
                r = subprocess.run(['amixer','sget',mixer], capture_output=True, timeout=0.4, text=True)
                if r.returncode == 0:
                    m = re.search(r'(\d+)%', r.stdout)
                    if m: return int(m.group(1))
            except Exception: pass
        return None

    def _read_battery(self):
        try:
            with open('/tmp/battery.percent') as f:
                return max(0, min(100, int(f.read().strip())))
        except Exception: return None

    def _vol_worker(self):
        last_bat = 0.0
        while self.running:
            locked = self.screen_locked
            v = self._read_volume()
            if v is not None and v != self._volume:
                self._volume = v
                if not locked:
                    self._volume_shown_until = time.monotonic() + 2.0
            now = time.monotonic()
            if now - last_bat >= 30.0:
                last_bat = now
                self._battery = self._read_battery()
            time.sleep(5.0 if locked else 1.0)

    def _find_folder_art(self, path):
        folder = os.path.dirname(path)
        try: files = os.listdir(folder)
        except OSError: return None
        preferred = {'cover','folder','album','front','artwork'}
        img_exts = {'.jpg','.jpeg','.png'}
        for f in files:
            name, ext = os.path.splitext(f)
            if name.lower() in preferred and ext.lower() in img_exts: return os.path.join(folder, f)
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in img_exts: return os.path.join(folder, f)
        return None

    def _fetch_info(self, path):
        try:
            r = subprocess.run(['ffprobe','-v','error','-show_entries','format=bit_rate:stream=codec_name,sample_rate','-of','json',path],capture_output=True,timeout=3)
            d = json.loads(r.stdout)
            br = int(d.get('format',{}).get('bit_rate',0)) // 1000
            st = next((s for s in d.get('streams',[]) if s.get('codec_name')), {})
            return {'bitrate':br, 'codec':st.get('codec_name','').upper(), 'sample_rate':int(st.get('sample_rate',0))}
        except Exception: return {}

    def _try_reconnect(self):
        if not os.path.exists(self.socket_path): return
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(1)
            s.connect(self.socket_path)
        except OSError: return
        cur = self.state.get('current')
        if not cur or not os.path.isfile(cur): s.close(); return
        # Synchronously query current playback state so UI is correct from frame 1
        results = {}
        try:
            props = {'time-pos':1,'duration':2,'pause':3,'playlist-playing-pos':4}
            cmd = b''.join(json.dumps({'command':['get_property',p],'request_id':i}).encode()+b'\n' for p,i in props.items())
            s.sendall(cmd)
            buf = b''; deadline = time.monotonic()+1.0
            while len(results) < len(props) and time.monotonic() < deadline:
                try: chunk = s.recv(4096)
                except OSError: break
                if not chunk: break
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n',1)
                    try:
                        m = json.loads(line)
                        rid = m.get('request_id')
                        if rid in props.values() and m.get('error')=='success':
                            results[rid] = m.get('data')
                    except ValueError: pass
        except OSError: pass
        finally: s.close()
        self.current = cur; self.queue = self.state.get('queue',[])
        if self.current not in self.queue: self.queue = [self.current]
        # If playlist advanced while backgrounded, update current track
        ppos = results.get(4)
        if isinstance(ppos,int) and 0 <= ppos < len(self.queue) and os.path.isfile(self.queue[ppos]):
            self.queue_index = ppos
            self.current = self.queue[ppos]
        else:
            self.queue_index = self.queue.index(self.current) if self.current in self.queue else 0
        pos = results.get(1); dur = results.get(2)
        self.position = float(pos) if isinstance(pos,(int,float)) and math.isfinite(pos) else 0.0
        self.duration = float(dur) if isinstance(dur,(int,float)) and math.isfinite(dur) else 0.0
        self.paused = bool(results.get(3,False))
        self.loaded = True; self.view = self.state.get('default_view','tape')
        self.pending = b''; self.buffer = b''; self.deadline = time.monotonic()+30; self._owns_mpv = False
        self.current_info = self._fetch_info(self.current)
        # Load cover from cache or temp file (no ffmpeg at startup)
        h = hashlib.md5((self.current+':64').encode()).hexdigest()
        cached = self._existing_cover_path(self._cover_cache_path(h))
        if cached and os.path.isfile(cached):
            try: self.cover = pygame.image.load(cached)
            except pygame.error: pass
        elif os.path.isfile('/tmp/walkman-cover.png'):
            try: self.cover = pygame.image.load('/tmp/walkman-cover.png')
            except pygame.error: pass
        self._start_viz_analysis(self.current)
        LOG.info('reconnected mpv; current=%s pos=%.1f dur=%.1f', self.current, self.position, self.duration)

    def _cover_worker(self):
        while self.running:
            with self._cover_lock:
                item = self._cover_queue.pop(0) if self._cover_queue else None
            if item is None: time.sleep(0.05); continue
            key, paths = item
            if key in self.group_covers or key in self._cover_ready: continue
            found = None
            if isinstance(key, tuple) and key[0] == 'Artists':
                artist_cached = self._existing_cover_path(self._artist_cache_path(key[1]))
                if artist_cached and os.path.isfile(artist_cached):
                    found = artist_cached
            for path in paths[:5]:
                if found:
                    break
                h = hashlib.md5((path+':48').encode()).hexdigest()
                cached = self._cover_cache_path(h)
                if not os.path.isfile(cached):
                    try: subprocess.run(['ffmpeg','-v','error','-i',path,'-map','0:v:0','-frames:v','1','-vf','scale=48:48:force_original_aspect_ratio=decrease,pad=48:48:(ow-iw)/2:(oh-ih)/2','-q:v','8',cached],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
                    except (OSError, subprocess.SubprocessError): pass
                if os.path.isfile(cached): found = cached; break
            if not found:
                seen = set()
                for path in paths[:5]:
                    d = os.path.dirname(path)
                    if d in seen: continue
                    seen.add(d); img = self._find_folder_art(path)
                    if img:
                        h = hashlib.md5((img+':48').encode()).hexdigest()
                        cached = self._cover_cache_path(h)
                        if not os.path.isfile(cached):
                            try: subprocess.run(['ffmpeg','-v','error','-i',img,'-vf','scale=48:48:force_original_aspect_ratio=decrease,pad=48:48:(ow-iw)/2:(oh-ih)/2','-q:v','8',cached],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
                            except (OSError, subprocess.SubprocessError): pass
                        if os.path.isfile(cached): found = cached; break
            with self._cover_lock:
                if key not in self.group_covers: self._cover_ready[key] = found

    def _flush_covers(self):
        with self._cover_lock:
            ready = list(self._cover_ready.items()); self._cover_ready.clear()
        for key, path in ready:
            if isinstance(key, tuple) and len(key) == 2 and key[0] == '_cur_':
                # current-track cover posted by _extract_cover_bg
                if key[1] == self.current and path and os.path.isfile(path):
                    try:
                        self.cover = pygame.image.load(path)
                        self.design._thumb_cache.clear()
                        self.design._thumb_keys.clear()
                    except pygame.error: pass
            elif path:
                try: self.group_covers[key] = pygame.image.load(path)
                except pygame.error: self.group_covers[key] = None
            else: self.group_covers[key] = None

    def track_title(self, path=None):
        path = path or self.current
        return self.metadata.get(path,{}).get('title') or (os.path.splitext(os.path.basename(path))[0] if path else 'Choose your music')

    def artist(self): return self.metadata.get(self.current,{}).get('artist') or 'Local music'
    def album(self): return self.metadata.get(self.current,{}).get('album') or 'Unknown album'
    @staticmethod
    def time_label(seconds): return '%02d:%02d'%(int(seconds)//60, int(seconds)%60)

    def queue_position_label(self):
        if not self.current or not self.queue:
            return ''
        index = getattr(self, 'queue_index', None)
        if not isinstance(index, int) or not 0 <= index < len(self.queue):
            try: index = self.queue.index(self.current)
            except ValueError: index = 0
        return '%d / %d' % (index + 1, len(self.queue))

    def save(self):
        tmp = self._state_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as _f: json.dump(self.state, _f)
        os.replace(tmp, self._state_path)

    def _cover_cache_path(self, digest):
        """All newly generated artwork uses compact, lossy JPEG files."""
        return os.path.join(self._covers_dir, digest + '.jpg')

    @staticmethod
    def _existing_cover_path(path):
        if os.path.isfile(path):
            return path
        legacy = os.path.splitext(path)[0] + '.png'
        return legacy if os.path.isfile(legacy) else None

    def build_viz_cache(self):
        if self._fetch_status is not None: return
        self._viz_build_cancel = False
        threading.Thread(target=self._build_viz_cache_worker, daemon=True).start()

    def _build_viz_cache_worker(self):
        candidates = [p for p in self.tracks if os.path.isfile(p)]
        total = len(candidates); done = 0
        self._fetch_status = 'Building visualizer cache...\n0/%d' % total
        try:
            for path in candidates:
                if self._viz_build_cancel: break
                self._fetch_status = 'Processing viz: %s\n%d of %d' % (os.path.basename(path)[:34], done+1, total)
                vpath = self._viz_cache_path(path)
                valid_cache = self._viz_cache_valid(vpath)
                if not valid_cache:
                    try: self._analyze_track(path)
                    except (OSError, subprocess.SubprocessError): pass
                done += 1
                self._fetch_status = 'Building visualizer cache...\n%d/%d' % (done, total)
        finally:
            label = 'Visualizer cache canceled' if self._viz_build_cancel else 'Visualizer cache ready'
            self._fetch_status = '%s\n%d/%d tracks processed' % (label, done, total)
            time.sleep(1.5)
            self._fetch_status = None

    def show(self, heading, rows, push=True):
        if push: self.stack.append((self.view, self.heading, self.rows, self.sel))
        self.heading = heading; self.rows = rows; self.sel = 0; self.view = 'list'

    # `paths` is the library snapshot produced by scan().  Do not test the
    # filesystem again while drawing a list: a momentary SD-card lookup miss
    # could otherwise make an already-scanned song vanish until the next scan.
    def song_rows(self, paths): return [(self.track_title(p),'track',p) for p in paths]
    def media_rows(self, paths): return [(os.path.splitext(os.path.basename(p))[0], 'media', p) for p in paths if os.path.isfile(p)]

    @staticmethod
    def queue_from_selection(paths, selected, shuffle=False):
        """Start a fresh queue at the selected item, keeping its full list."""
        paths = list(paths)
        try:
            index = paths.index(selected)
        except ValueError:
            return paths
        if shuffle:
            remaining = paths[:index] + paths[index + 1:]
            random.shuffle(remaining)
            return [selected] + remaining
        return paths[index:] + paths[:index]

    def category(self, label):
        if label == 'All Songs': self.show(label, self.song_rows(self.tracks))
        elif label == 'Media':
            self.show(label, self.media_rows(self.media))
            with self._cover_lock:
                queued = {k for k,_ in self._cover_queue}
                for path in self.media:
                    key = ('media', path)
                    if key not in self.group_covers and key not in self._cover_ready and key not in queued:
                        self._cover_queue.append((key, [path]))
        elif label in ('Albums','Artists'):
            key = 'album' if label == 'Albums' else 'artist'; groups = {}
            for p in self.tracks: groups.setdefault(self.metadata.get(p,{}).get(key) or 'Unknown '+key, []).append(p)
            self.show(label, [(name,'group',paths) for name,paths in sorted(groups.items())])
            with self._cover_lock:
                queued = {k for k,_ in self._cover_queue}
                for name, paths in groups.items():
                    gkey = (label, name)
                    if gkey not in self.group_covers and gkey not in self._cover_ready and gkey not in queued:
                        self._cover_queue.append((gkey, paths))
        elif label in ('Favorites','Recent'): self.show(label, self.song_rows(self.state[label.lower()]))
        elif label == 'Playlists': self.show(label, [(os.path.basename(p),'playlist',p) for p in self.playlists])
        elif label == 'Settings': self.settings()

    def start_search(self):
        if self.view != 'list' or self.heading not in ('All Songs', 'Media', 'Albums', 'Artists'):
            return
        self._search = {
            'scope': self.heading,
            'query': '',
            'layer': 0,
            'x': 0,
            'y': 0,
            'message': '',
            'return': (self.view, self.heading, self.rows, self.sel),
        }
        self.view = 'search'

    def cancel_search(self):
        if not self._search:
            self.view = 'home'
            return
        self.view, self.heading, self.rows, self.sel = self._search['return']
        self._search = None

    def search_results(self, scope, query):
        term = query.casefold()
        if scope == 'All Songs':
            paths = [path for path in self.tracks if term in ' '.join((
                self.track_title(path),
                self.metadata.get(path, {}).get('artist', ''),
                self.metadata.get(path, {}).get('album', ''),
            )).casefold()]
            return self.song_rows(paths)
        if scope == 'Media':
            return self.media_rows([path for path in self.media if term in os.path.basename(path).casefold()])
        group_key = 'album' if scope == 'Albums' else 'artist'
        unknown = 'Unknown ' + group_key
        groups = {}
        for path in self.tracks:
            name = self.metadata.get(path, {}).get(group_key) or unknown
            if term in name.casefold():
                groups.setdefault(name, []).append(path)
        return [(name, 'group', paths) for name, paths in sorted(groups.items(), key=lambda item: item[0].casefold())]

    def submit_search(self):
        if not self._search:
            return
        query = self._search['query'].strip()
        if not query:
            self._search['message'] = 'Type something to search'
            return
        scope = self._search['scope']
        returned_view, returned_heading, returned_rows, returned_sel = self._search['return']
        self.view, self.heading, self.rows, self.sel = returned_view, returned_heading, returned_rows, returned_sel
        self._search = None
        self.show('Search: ' + query, self.search_results(scope, query))

    def search_action(self, action):
        page = self._search
        if not page:
            return
        if action == 'b':
            self.cancel_search()
            return
        if action == 'search':
            self.submit_search()
            return
        if action == 'search_shift':
            page['layer'] = 1 - page['layer']
            return
        if action == 'x':
            page['layer'] = 1 - page['layer']
            return
        if action == 'y':
            page['query'] = page['query'][:-1]
            return
        if action == 'a':
            key = SEARCH_LAYERS[page['layer']][page['y']][page['x']]
            page['query'] = page['query'][:-1] if key == '←' else page['query'] + key
            return
        if action == 'quit':
            self.submit_search()
            return
        if action in ('left', 'right', 'up', 'down'):
            if action == 'left': page['x'] = (page['x'] - 1) % len(SEARCH_LAYERS[page['layer']][page['y']])
            elif action == 'right': page['x'] = (page['x'] + 1) % len(SEARCH_LAYERS[page['layer']][page['y']])
            else:
                page['y'] = (page['y'] + (-1 if action == 'up' else 1)) % len(SEARCH_LAYERS[page['layer']])
                page['x'] = min(page['x'], len(SEARCH_LAYERS[page['layer']][page['y']]) - 1)
            self._play_sound(self._snd_nav)

    def settings(self):
        saved_sel = self.sel if self.heading == 'Settings' else 0
        self.show('Settings', [
            ('Playback', 'header', None),
            ('⇄  Shuffle: '+('On' if self.state.get('shuffle') else 'Off'), 'shuffle', None),
            ('↻  Repeat: '+('On' if self.state.get('repeat') else 'Off'), 'repeat', None),
            ('♪  Sounds: '+('On' if self.state.get('sounds', True) else 'Off'), 'sounds', None),
            ('▶  Default view: '+('Viz' if self.state.get('default_view','tape')=='viz' else 'Cassette'), 'default_view', None),
            ('◑  Lock dim: '+self.state.get('lock_dim','Medium'), 'lock_dim', None),
            ('Appearance', 'header', None),
            ('◑  Theme: '+self.state.get('theme','Cassette'), 'theme', None),
            ('◇  Accent color...', 'open_picker', None),
            ('◈  Dynamic visualizer: '+('On' if self.state.get('dynamic_viz') else 'Off'), 'dynamic_viz', None),
            ('Library', 'header', None),
            ('Library database: '+{'sqlite': 'SQLite (bundled)', 'dbm': 'dbm fallback', 'json': 'JSON fallback'}.get(self._metadata_backend, self._metadata_backend), 'info', None),
            ('▣  Browse music folders', 'folders', None),
            ('◈  Build visualizer cache', 'build_viz', None),
            ('↺  Rescan music', 'rescan', None),
            ('⊡  Fetch cover art...', 'fetch_art_menu', None),
            ('◉  Fetch artist photos...', 'fetch_artist_art_menu', None),
            ('⊘  Clear metadata cache', 'clear_cache', None),
            ('⊠  Clear cover art cache', 'clear_covers', None),
            ('⊠  Clear visualizer cache', 'clear_viz', None),
        ], push=self.heading != 'Settings')
        self.sel = saved_sel
        while self.sel < len(self.rows) and self.rows[self.sel][1] == 'header':
            self.sel += 1
        self.sel = min(self.sel, len(self.rows)-1)

    def folder(self, path):
        dirs = sorted(p for p in glob.glob(os.path.join(path,'*')) if os.path.isdir(p))
        self.show(os.path.basename(path), [(os.path.basename(p),'folder',p) for p in dirs]+self.song_rows([p for p in self.tracks if os.path.dirname(p)==path]))

    def stop(self, keep_mpv=False):
        if self.sock: self.sock.close(); self.sock = None
        if keep_mpv: self.proc = None; self._owns_mpv = False; return
        if self._owns_mpv and self.proc:
            if self.proc.poll() is None:
                # mpv may be running inside systemd-inhibit. Stop its whole
                # process group so the player cannot keep running after a
                # normal Walkman exit.
                try: os.killpg(self.proc.pid, signal.SIGTERM)
                except (AttributeError, OSError): self.proc.terminate()
                try: self.proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try: os.killpg(self.proc.pid, signal.SIGKILL)
                    except (AttributeError, OSError): self.proc.kill()
                    self.proc.wait()
        elif not self._owns_mpv and self.current:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(1)
                s.connect(self.socket_path); s.sendall(json.dumps({'command':['quit']}).encode()+b'\n'); s.close()
            except OSError: pass
        self.proc = None; self._owns_mpv = False

    def _album_cache_path(self, path):
        meta = self.metadata.get(path, {})
        ar = meta.get('artist','').strip(); al = meta.get('album','').strip()
        if not ar or not al: return None
        return self._cover_cache_path(hashlib.md5(f'{ar}:{al}:64'.encode()).hexdigest())

    def _load_cover_for(self, path):
        self.cover = None
        h = hashlib.md5((path+':64').encode()).hexdigest()
        cached = self._cover_cache_path(h)
        # Fast path 1: track-specific cache
        existing = self._existing_cover_path(cached)
        if existing:
            try: self.cover = pygame.image.load(existing); return
            except pygame.error: pass
        # Fast path 2: album-level cache (shared across tracks on same album)
        alb = self._album_cache_path(path)
        existing_album = self._existing_cover_path(alb) if alb else None
        if existing_album:
            if existing_album == alb:
                try:
                    import shutil; shutil.copy2(existing_album, cached)
                except OSError: pass
            try: self.cover = pygame.image.load(existing_album); return
            except pygame.error: pass
        # Slow path: background extraction thread so poll() never blocks
        threading.Thread(target=self._extract_cover_bg, args=(path, cached), daemon=True).start()

    def _extract_cover_bg(self, path, cached):
        result = None
        tmp = f'/tmp/walkman-cover-{threading.get_ident()}.jpg'
        try: os.unlink(tmp)
        except OSError: pass
        try:
            subprocess.run(['ffmpeg','-v','error','-i',path,'-map','0:v:0','-frames:v','1',
                           '-vf','scale=64:64:force_original_aspect_ratio=increase,crop=64:64','-q:v','8',tmp],
                          stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
            if os.path.isfile(tmp):
                try:
                    import shutil; shutil.copy2(tmp, cached); result = cached
                except OSError: result = tmp
        except (OSError, subprocess.SubprocessError): pass
        if not result:
            img = self._find_folder_art(path)
            if img:
                ih = hashlib.md5((img+':64').encode()).hexdigest()
                icached = self._cover_cache_path(ih)
                if not os.path.isfile(icached):
                    try:
                        subprocess.run(['ffmpeg','-v','error','-i',img,
                                       '-vf','scale=64:64:force_original_aspect_ratio=increase,crop=64:64','-q:v','8',icached],
                                      stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
                    except (OSError, subprocess.SubprocessError): pass
                if os.path.isfile(icached):
                    try:
                        import shutil; shutil.copy2(icached, cached)
                    except OSError: pass
                    result = icached
        # Also save to album-level cache so other tracks on the same album skip extraction
        if result:
            alb = self._album_cache_path(path)
            if alb and not os.path.isfile(alb):
                try:
                    import shutil; shutil.copy2(result, alb)
                except OSError: pass
        # Post result back to main thread via cover_ready
        with self._cover_lock:
            self._cover_ready[('_cur_', path)] = result

    def play(self, path):
        self.media_type = 'video' if os.path.splitext(path)[1].lower() in MEDIA_EXTENSIONS else 'audio'
        if self.media_type == 'video': self._video_return_view = self.view
        self.stop()
        start = self.queue.index(path) if path in self.queue else 0
        try:
            if os.path.exists(self.socket_path): os.unlink(self.socket_path)
        except OSError: pass
        m3u = '/tmp/walkman-queue.m3u'
        try:
            with open(m3u,'w',encoding='utf-8') as f: f.write('\n'.join(self.queue)+'\n')
            extra = ['--loop-playlist=inf'] if self.state.get('repeat') else []
            flags = ['--fullscreen','--osd-level=1'] if self.media_type == 'video' else ['--no-video','--audio-display=no']
            if self.media_type == 'video':
                input_conf = '/tmp/walkman-video-input.conf'
                try:
                    with open(input_conf, 'w', encoding='utf-8') as f:
                        f.write('ESC quit\nq quit\nBACKSPACE quit\nx quit\n')
                    flags += ['--force-window=yes', '--input-conf='+input_conf,
                              '--input-default-bindings=no', '--input-vo-keyboard=no',
                              '--hwdec=auto-safe', '--framedrop=vo', '--cache=yes',
                              '--cache-pause=no', '--video-sync=audio', '--audio-buffer=1',
                              '--cache-secs=30', '--demuxer-max-bytes=128MiB',
                              '--demuxer-max-back-bytes=64MiB']
                except OSError: pass
            cmd = ['mpv','--no-config',*flags,'--input-terminal=no',
                   '--really-quiet','--input-ipc-server='+self.socket_path,
                   '--playlist='+m3u,'--playlist-start='+str(start)]+extra
        except (OSError, ValueError):
            flags = [] if self.media_type == 'video' else ['--no-video','--audio-display=no']
            cmd = ['mpv','--no-config',*flags,'--idle=yes','--keep-open=no',
                   '--input-terminal=no','--really-quiet','--input-ipc-server='+self.socket_path,'--',path]
        # Keep the KNULLI sleep block only for this mpv lifetime. This wrapper
        # survives SELECT background playback without keeping the launcher
        # open, then removes the marker as soon as mpv exits.
        if self.media_type == 'audio':
            cmd = ['/bin/sh', '-c', '"$@"; code=$?; rm -f /var/run/battery-saver/walkman.pause; exit $code',
                   'walkman-mpv', *cmd]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self._owns_mpv = True
        self.current = path; self.queue_index = start; self.position = 0.; self.duration = 0.; self.paused = False
        self.loaded = False; self.pending = b''; self.buffer = b''; self.deadline = time.monotonic()+8; self.view = self.state.get('default_view','tape')
        if self.media_type == 'audio':
            self._load_cover_for(path)
            self._start_viz_analysis(path)
        else:
            self.cover = None
            self._viz_data = []
            self._viz_bars = [0.0] * _VIZ_N
        self.current_info = self._fetch_info(path)
        self.state['recent'] = [path]+[p for p in self.state['recent'] if p!=path][:99]
        self.state['queue'] = self.queue; self.state['current'] = path; self.save()
        if self.media_type == 'video':
            self._run_video_foreground()

    def _run_video_foreground(self):
        """Give mpv exclusive display/input ownership, as Jellyfin does."""
        event_struct = struct.Struct('@llHHi')
        button_actions = {304: 'pause', 305: 'stop', 310: 'pause', 312: 'stop',
                          308: 'seek:-30', 314: 'seek:-60', 315: 'seek:60'}
        devices = {}
        try:
            for path in sorted(glob.glob('/dev/input/event*')):
                name_path = '/sys/class/input/' + os.path.basename(path) + '/device/name'
                try:
                    with open(name_path, encoding='utf-8') as f:
                        if f.read().strip() != 'Anbernic RG35XX-H Controller': continue
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK); devices[fd] = bytearray()
                except OSError: pass
            pygame.display.quit()
            while self.proc and self.proc.poll() is None:
                for fd in select.select(list(devices), [], [], 0.02)[0]:
                    try: devices[fd].extend(os.read(fd, event_struct.size * 32))
                    except BlockingIOError: continue
                    while len(devices[fd]) >= event_struct.size:
                        _, _, kind, code, value = event_struct.unpack_from(devices[fd])
                        del devices[fd][:event_struct.size]
                        if kind != 1 or value != 1: continue
                        action = button_actions.get(code)
                        if action == 'stop':
                            # Drop queued seek/pause commands so B always exits
                            # the current file instead of affecting the playlist.
                            self.pending = b''
                            self.command('quit')
                            if self.pending and self.sock:
                                try: self.sock.send(self.pending)
                                except OSError: pass
                                self.pending = b''
                            return
                        elif action == 'pause': self.command('cycle', 'pause')
                        elif action and action.startswith('seek:'):
                            self.command('seek', int(action.split(':', 1)[1]), 'relative+exact')
                self.poll()
        finally:
            for fd in devices:
                try: os.close(fd)
                except OSError: pass
            self.stop()
            pygame.display.init()
            self.screen = pygame.display.set_mode((640, 480), 0 if self.preview else pygame.FULLSCREEN)
            # Controller events generated while mpv owned the display must not
            # be replayed by Walkman as delayed Next/Previous actions.
            pygame.event.clear()
            self.design = Design(self.screen)
            self._apply_theme()
            self.view = self._video_return_view

    def command(self, *args, request_id=None):
        message = {'command': list(args)}
        if request_id is not None: message['request_id'] = request_id
        self.pending += json.dumps(message).encode()+b'\n'

    def next(self, delta=1, automatic=False):
        if not self.queue: return
        index = self.queue.index(self.current) if self.current in self.queue else -1
        index += delta
        if automatic and index >= len(self.queue) and not self.state.get('repeat'): self.paused = True; return
        self.play(self.queue[index%len(self.queue)])

    def poll(self):
        if not self.current: return
        if self.proc and self.proc.poll() is not None: self.paused = True; return
        if not self.sock:
            candidate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); candidate.settimeout(.005)
            try: candidate.connect(self.socket_path)
            except OSError:
                candidate.close()
                if time.monotonic() > self.deadline: self.stop(); self.paused = True
                return
            self.sock = candidate; self.sock.setblocking(False)
            for i, key in enumerate(('time-pos','duration','pause','metadata','playlist-playing-pos')):
                self.command('observe_property', i, key)
            self._state_refresh_at = time.monotonic()
        # mpv may occasionally miss observe_property notifications. Poll the
        # values used by the progress UI as a recovery path.
        if time.monotonic() >= getattr(self, '_state_refresh_at', 0):
            self.command('get_property', 'time-pos', request_id=101)
            self.command('get_property', 'duration', request_id=102)
            self._state_refresh_at = time.monotonic() + 0.5
        try:
            if self.pending:
                try: n = self.sock.send(self.pending); self.pending = self.pending[n:]
                except BlockingIOError: pass
            for _ in range(8):
                try: data = self.sock.recv(16384)
                except BlockingIOError: break
                if not data: break
                self.buffer += data
                while b'\n' in self.buffer:
                    raw, self.buffer = self.buffer.split(b'\n', 1)
                    try: m = json.loads(raw)
                    except ValueError: continue
                    if m.get('event') == 'file-loaded': self.loaded = True
                    if m.get('request_id') in (101, 102) and m.get('error') == 'success':
                        value = m.get('data')
                        if isinstance(value, (int, float)) and math.isfinite(value):
                            if m['request_id'] == 101:
                                self.position = max(0.0, float(value)); self.loaded = True
                            else:
                                self.duration = max(0.0, float(value))
                    if m.get('event') == 'property-change':
                        key = m.get('name'); value = m.get('data')
                        if key in ('time-pos','duration') and isinstance(value,(int,float)) and math.isfinite(value):
                            setattr(self, 'position' if key=='time-pos' else 'duration', value)
                            if key == 'time-pos': self.loaded = True
                        elif key == 'pause' and isinstance(value, bool): self.paused = value
                        elif key == 'metadata' and isinstance(value, dict):
                            self.metadata[self.current] = {str(k).lower():str(v) for k,v in value.items()}
                        elif key == 'playlist-playing-pos' and isinstance(value, (int, float)):
                            idx = int(value)
                            if not (0 <= idx < len(self.queue)): continue
                            self.queue_index = idx
                            new_path = self.queue[idx]
                            if new_path != self.current:
                                self.current = new_path
                                self.media_type = 'video' if os.path.splitext(new_path)[1].lower() in MEDIA_EXTENSIONS else 'audio'
                                self.position = 0.; self.duration = 0.; self.loaded = False
                                self.current_info = self._fetch_info(new_path)
                                if self.media_type == 'audio':
                                    self._load_cover_for(new_path)
                                    self._start_viz_analysis(new_path)
                                else:
                                    self.cover = None; self._viz_data = []
                                self.state['current'] = new_path; self.save()
        except OSError:
            # Reconnect IPC next frame; keep mpv alive through transient socket errors.
            try: self.sock.close()
            except (AttributeError, OSError): pass
            self.sock = None

    def _begin_exit(self, keep_mpv):
        """Show a short confirmation before returning to KNULLI."""
        self._exit_keep_mpv = keep_mpv
        if keep_mpv and self.current and self.media_type == 'audio':
            title, detail = 'PLAYING IN BACKGROUND', 'Music will keep playing'
        elif keep_mpv:
            title, detail = 'RETURNING TO KNULLI', 'Walkman is closing'
        else:
            title, detail = 'EXITING WALKMAN', 'Stopping playback'
        LOG.info('exit requested; background=%s current=%s', keep_mpv, bool(self.current))
        self._exit_notice = (title, detail, time.monotonic() + 0.85)
        self._play_sound(self._snd_back)

    def act(self, action):
        LOG.info('act: %s locked=%s', action, self.screen_locked)
        if self._exit_notice is not None:
            return
        if self.screen_locked:
            if action == 'screen_lock_down':
                if self._r1_down_at is None: self._r1_down_at = time.monotonic()
            elif action == 'screen_lock_up':
                if self._r1_down_at and time.monotonic() - self._r1_down_at >= 0.9:
                    self._unlock_screen()
                self._r1_down_at = None
            return
        if action == 'quit': self._begin_exit(False)
        elif action == 'background': self._begin_exit(True)
        elif action == 'screen_lock_down':
            if self.screen_locked:
                if self._r1_down_at is None: self._r1_down_at = time.monotonic()
            else:
                self._lock_screen(); self._r1_down_at = None
        elif self.view == 'search':
            self.search_action(action)
        elif action == 'search':
            self.start_search()
        elif action == 'stop_playback':
            self.stop()
            self.current = None; self.queue = []; self.queue_index = 0; self.position = 0.; self.duration = 0.; self.paused = True
            self.state['current'] = None; self.state['queue'] = []; self.save()
            self.view = 'home'
        elif action == 'pause_toggle':
            if self.current:
                self.command('cycle', 'pause')
                self.paused = not self.paused
        elif action == 'b':
            if self.media_type == 'video' and self.proc and self.proc.poll() is None:
                self.command('quit')
                return
            self._play_sound(self._snd_back)
            if self._fetch_status is not None:
                self._fetch_cancel = True; self._viz_build_cancel = True; return
            if self.view == 'picker': self._apply_theme(); self.view = 'list'
            elif self.view == 'list' and self.stack: self.view, self.heading, self.rows, self.sel = self.stack.pop()
            else: self.view = 'home'
        elif action == 'x' and self.current:
            if self.view in ('tape','viz'): self.view = 'details'
            elif self.view == 'details': self.view = self.state.get('default_view','tape')
            elif self.view in ('list','home'): self.view = self.state.get('default_view','tape')
        elif action == 'y' and self.view not in ('home', 'list') and self.current:
            fav = self.state['favorites']
            if self.current in fav: fav.remove(self.current)
            else: fav.append(self.current)
            self.save()
        elif action == 'y' and self.view in ('home', 'list'):
            self.settings()
        elif action in ('prev','next'):
            if self.view == 'picker':
                self._picker_hue = (self._picker_hue + (-30 if action=='prev' else 30)) % 360
                self.design.set_accent(Design._hsv_to_rgb(self._picker_hue, 0.72, 0.90))
            elif self.current: self.next(-1 if action=='prev' else 1)
        elif action in ('left','right','up','down'):
            if self.view == 'picker' and action in ('left','right'):
                self._picker_hue = (self._picker_hue + (-5 if action=='left' else 5)) % 360
                self.design.set_accent(Design._hsv_to_rgb(self._picker_hue, 0.72, 0.90))
            elif self.view == 'viz' and action in ('up','down'):
                _styles = ['Bars','Mirror','Wave','Radial']
                _cur = self.state.get('viz_style','Bars')
                _d = -1 if action == 'up' else 1
                self.state['viz_style'] = _styles[(_styles.index(_cur)+_d)%len(_styles)] if _cur in _styles else _styles[0]
                self.save()
            elif self.view in ('tape','details','viz') and self.current and action in ('left','right'):
                self.next(-1 if action=='left' else 1)
            elif self.view == 'home':
                row, col = divmod(self.home_sel, 4)
                if action == 'left': col = (col-1)%4
                elif action == 'right': col = (col+1)%4
                else: row = 1-row
                self.home_sel = row*4+col
                self._play_sound(self._snd_nav)
            elif self.view == 'list' and self.rows:
                delta = -1 if action in ('up','left') else 1
                new_sel = (self.sel + delta) % len(self.rows)
                attempts = 0
                while self.rows[new_sel][1] == 'header' and attempts < len(self.rows):
                    new_sel = (new_sel + delta) % len(self.rows); attempts += 1
                self.sel = new_sel
                self._sel_flash_t = time.monotonic()
                self._play_sound(self._snd_nav)
        elif action == 'a':
            self._play_sound(self._snd_sel)
            if self.view == 'picker':
                self.state['custom_hue'] = self._picker_hue; self.state['theme'] = 'Custom'
                self._apply_theme(); self.save(); self.settings()
            elif self.view == 'home': self.stack = []; self.category(self.categories[self.home_sel])
            elif self.view in ('tape','details','viz'): self.command('cycle','pause')
            elif self.rows:
                label, kind, value = self.rows[self.sel]
                if kind in ('track', 'media'):
                    items = [p for _,k,p in self.rows if k == kind]
                    self.queue = self.queue_from_selection(items, value, self.state.get('shuffle'))
                    self.play(value)
                elif kind == 'group': self.show(label, self.song_rows(value))
                elif kind == 'folder': self.folder(value)
                elif kind == 'playlist':
                    with open(value, encoding='utf-8-sig', errors='replace') as f:
                        paths = [os.path.abspath(os.path.join(os.path.dirname(value),s.strip())) for s in f if s.strip() and not s.lstrip().startswith('#')]
                    self.show(label, self.song_rows(paths))
                elif kind == 'rescan':
                    self._scanning = True; self.draw(); pygame.display.flip()
                    self.scan(); self._scanning = False; self.settings()
                elif kind == 'folders':
                    self.folder(MUSIC)
                elif kind == 'fetch_art_menu':
                    self.show('Fetch Cover Art', [
                        ('◈  Missing only', 'fetch_art', 'missing'),
                        ('◈  All tracks',   'fetch_art', 'all'),
                    ])
                elif kind == 'fetch_art':
                    self._fetch_cancel = False
                    self._fetch_status = 'Connecting...'
                    threading.Thread(target=self._fetch_art_worker, args=(value,), daemon=True).start()
                elif kind == 'fetch_artist_art_menu':
                    self.show('Fetch Artist Photos', [
                        ('◈  Missing only', 'fetch_artist_art', 'missing'),
                        ('◈  Refresh all',  'fetch_artist_art', 'all'),
                    ])
                elif kind == 'fetch_artist_art':
                    self._fetch_cancel = False
                    self._fetch_status = 'Connecting...'
                    threading.Thread(target=self._fetch_artist_art_worker, args=(value,), daemon=True).start()
                elif kind == 'info':
                    pass
                elif kind == 'build_viz':
                    self.build_viz_cache()
                elif kind == 'clear_cache':
                    self._scanning = True; self.draw(); pygame.display.flip()
                    for cache_file in MetadataStore.cache_files(self._dbm_path, self._cache_path):
                        try: os.unlink(cache_file)
                        except OSError: pass
                    self.metadata = {}; self.scan()
                    self._scanning = False; self.settings()
                elif kind == 'clear_covers':
                    self._scanning = True; self.draw(); pygame.display.flip()
                    import glob as _glob
                    for f in _glob.glob(os.path.join(self._covers_dir, '*.png')) + _glob.glob(os.path.join(self._covers_dir, '*.jpg')):
                        try: os.unlink(f)
                        except OSError: pass
                    self.cover = None; self.group_covers = {}
                    self._scanning = False; self.settings()
                elif kind == 'clear_viz':
                    self._scanning = True; self.draw(); pygame.display.flip()
                    import glob as _glob
                    for f in _glob.glob(os.path.join(self._viz_dir, '*.viz*')):
                        try: os.unlink(f)
                        except OSError: pass
                    self._viz_data = []
                    self._scanning = False; self.settings()
                elif kind == 'theme':
                    keys = list(THEMES.keys()); cur = self.state.get('theme','Cassette')
                    nxt = keys[(keys.index(cur)+1)%len(keys)] if cur in keys else keys[0]
                    self.state['theme'] = nxt; self._apply_theme(); self.save(); self.settings()
                elif kind == 'open_picker':
                    self._picker_hue = float(self.state.get('custom_hue', 30))
                    self.design.set_accent(Design._hsv_to_rgb(self._picker_hue, 0.72, 0.90))
                    self.view = 'picker'
                elif kind == 'default_view':
                    self.state['default_view'] = 'viz' if self.state.get('default_view','tape') == 'tape' else 'tape'
                    self.save(); self.settings()
                elif kind == 'lock_dim':
                    opts = ['Off', 'Low', 'Medium', 'Dark']
                    cur = self.state.get('lock_dim', 'Medium')
                    nxt = opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]
                    self.state['lock_dim'] = nxt; self.save(); self.settings()
                else:
                    self.state[kind] = not self.state.get(kind, False); self.save(); self.settings()

    def draw(self):
        if self._exit_notice is not None:
            self.design.exit_notice(*self._exit_notice[:2])
            return
        if self.screen_locked:
            self.screen.fill((3, 4, 5))
            elapsed = time.monotonic() - self._lock_anim_started
            if self._lock_anim_kind == 'lock' and elapsed < .7:
                p = min(1.0, elapsed/.7); self.design.text('LOCKING', 320, 175, 20, (140,140,140), center=True)
                pygame.draw.arc(self.screen, (140,140,140), (290,195,60,55), math.pi, math.tau, 4)
                pygame.draw.rect(self.screen, (140,140,140), (280,225,80,55), 3, border_radius=6)
                pygame.draw.rect(self.screen, (140,140,140), (298,238,44,int(30*p)), border_radius=3)
            else:
                self.design.text('SCREEN LOCKED', 320, 210, 24, (140,140,140), center=True)
                self.design.text('Hold R1 to unlock', 320, 250, 18, (140,140,140), center=True)
            return
        if self._lock_anim_kind == 'unlock':
            elapsed = time.monotonic() - self._lock_anim_started
            if elapsed < .7:
                self.screen.fill((3, 4, 5)); p = min(1.0, elapsed/.7)
                self.design.text('UNLOCKED', 320, 175, 20, (180,180,180), center=True)
                pygame.draw.arc(self.screen, (180,180,180), (290,195,60,55), math.pi*(1-p), math.tau, 4)
                pygame.draw.rect(self.screen, (180,180,180), (280,225,80,55), 3, border_radius=6)
                return
            self._lock_anim_kind = None
        if self.media_type == 'video' and self.proc and self.proc.poll() is None:
            return
        if getattr(self,'_scanning',False) or self._fetch_status is not None:
            self.design.scanning(self); return
        {'home':self.design.dashboard,'list':self.design.listing,'tape':self.design.cassette,
         'viz':self.design.viz,'details':self.design.details,'picker':self.design.picker,
         'search':self.design.search}.get(self.view, self.design.dashboard)(self)
        self.design.volume_overlay(self)

    def loop(self):
        clock = pygame.time.Clock()
        try:
            while self.running:
                raw_lock = self._poll_screen_lock()
                locked = self.screen_locked
                dt = min(clock.tick(5 if locked else 30) / 1000, .5 if locked else .1)

                if self._exit_notice is not None:
                    self.draw(); pygame.display.flip()
                    if time.monotonic() >= self._exit_notice[2]: self.running = False
                    continue

                if locked:
                    # Apply dim once after the lock animation finishes
                    if not self._screen_dim_applied:
                        if time.monotonic() - self._lock_anim_started >= 0.7:
                            self._apply_lock_dim()
                    # Redraw only during the animation or the one frame after it settles
                    anim_active = (self._lock_anim_kind == 'lock' and
                                   time.monotonic() - self._lock_anim_started < 0.7)
                    if anim_active or not self._lock_drawn:
                        self.draw()
                        pygame.display.flip()
                        if not anim_active:
                            self._lock_drawn = True
                    pygame.event.clear()
                    self.poll()
                    continue

                if raw_lock:
                    pygame.event.clear()
                    events = []
                else:
                    events = pygame.event.get()
                for e in events:
                    action = None
                    if e.type == pygame.QUIT: action = 'quit'
                    elif e.type == pygame.JOYHATMOTION:
                        x, y = e.value; action = 'left' if x<0 else 'right' if x>0 else 'up' if y>0 else 'down' if y<0 else None
                    elif e.type == pygame.JOYBUTTONDOWN:
                        # SELECT is button 10 on the RG35XX H.  It exits the
                        # UI but deliberately leaves mpv running for music.
                        # START (11) remains the normal full app exit.
                        action = {3:'a',4:'b',6:'x',5:'y',7:'pause_toggle',9:'background',10:'background',11:'quit'}.get(e.button)
                    elif e.type == pygame.JOYBUTTONUP:
                        action = None
                    elif e.type == pygame.KEYDOWN:
                        action = {pygame.K_RETURN:'a',pygame.K_BACKSPACE:'b',pygame.K_ESCAPE:'quit',pygame.K_x:'x',pygame.K_y:'y',pygame.K_UP:'up',pygame.K_DOWN:'down',pygame.K_LEFT:'left',pygame.K_RIGHT:'right'}.get(e.key)
                    if action: self.act(action)
                self.poll(); self._flush_covers(); self._update_viz(dt)
                if self.current and not self.paused and self.loaded: self.angle = (self.angle+dt*1.5)%math.tau
                self.draw(); pygame.display.flip()
        finally:
            self._restore_brightness()
            self.stop(keep_mpv=self._exit_keep_mpv)
            for fd in self._lock_event_fds:
                try: os.close(fd)
                except OSError: pass
            pygame.quit()

if __name__ == '__main__':
    logging.basicConfig(filename=os.path.join(ROOT,'log.txt'),level=logging.INFO,format='%(asctime)s %(message)s')
    try:
        app = App()
        signal.signal(signal.SIGTERM, lambda *_: setattr(app,'running',False))
        app.loop()
    except Exception:
        LOG.exception('Walkman stopped because of an unhandled error')
        raise

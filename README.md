# Walkman RG35XX H

A cassette-style music and media player for the Anbernic RG35XX H, built as a
PortMaster port for KNULLI Linux.

## Features

- Plays MP3, FLAC, OGG, WAV, and M4A audio files.
- Browses videos and pictures from the `video` folder as one Media library.
- Supports common MP4, MKV, AVI, MOV, WebM, M4V, MPEG, JPG, PNG, GIF, BMP,
  and WebP files when supported by the device's `mpv` installation.
- Browses All Songs, Media, Albums, Artists, Folders, Favorites, Recent, and
  Playlists (`.m3u`/`.m3u8`).
- Shows cached album art and media thumbnails in the library.
- Uses a cassette view and four visualizer styles, with visualizer data built
  in the background and cached for later playback.
- Supports shuffle, repeat, favorites, playlists, background playback, and
  automatic queue advance.
- Provides a fullscreen Settings screen with theme, accent, playback, cache,
  library, and storage information.
- Uses JSON files for state and metadata. No database or device-side install
  is required.

## Installation

1. Install PortMaster on KNULLI.
2. Copy the `walkman/` folder to `roms/ports/` on the SD card.
3. Add audio files to `walkman/music/`.
4. Add videos and pictures to `walkman/video/`.
5. Launch **Walkman** from the Ports menu.

The music and media folders may be redirected with `WALKMAN_MUSIC` and
`WALKMAN_VIDEO` in `Walkman.sh`. The first launch scans the folders and creates
the local JSON metadata and cache files.

## Controls

| Button | Action |
|---|---|
| **A** | Play, pause, or confirm |
| **B** | Back or cancel; exit video playback |
| **X** | Toggle Now Playing and details |
| **Y** | Open Settings from the Library |
| **Up / Down** | Navigate; change visualizer style or accent hue |
| **Left / Right** | Previous / next track from player screens |
| **R1** | Lock the screen while audio continues |
| **Hold R1** | Unlock the screen |
| **L1** | Pause or resume audio |
| **START** | Exit the app |
| **SELECT** | Exit while keeping audio playback in the background |
| **Volume buttons** | Change device volume, including while locked |

While a video is playing, the video player owns the display and controller,
so the music visualizer and audio controls are not rendered underneath it.

## Cache layout

Walkman keeps generated data under `.cache/`:

```text
.cache/
├── metadata/
│   └── metadata.json
├── covers/
│   └── *.png
└── visualizer/
    └── *.viz
```

Settings can clear metadata, cover art, or visualizer data independently. The
visualizer builder reports the current file and overall progress and can be
cancelled with **B**.

## Requirements

- Anbernic RG35XX H running KNULLI Linux
- PortMaster
- Python 3 and pygame
- `mpv` for playback
- `ffmpeg` for cover extraction and visualizer analysis
- `mutagen` is optional and speeds up metadata scanning
- Network access is only needed for the optional MusicBrainz cover-art fetch

## Technical notes

- Audio playback uses `mpv` through its UNIX socket IPC interface.
- Video playback uses fullscreen `mpv` with hardware decoding, frame-drop,
  cache, and audio-sync settings tuned for the RG35XX H.
- Visualizer analysis uses numpy FFT when available and a pure-Python Goertzel
  fallback otherwise.
- Runtime state, metadata, artwork, and visualizer data remain local to the
  device and are excluded from Git and release packages.

## License

Walkman is released under the MIT License. The bundled DejaVu Sans font is
distributed with its license in `font-LICENSE.txt`.

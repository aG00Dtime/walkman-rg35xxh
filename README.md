# Walkman RG35XX H

Walkman is a local music and media player for the Anbernic RG35XX H running
KNULLI Linux. It is packaged as a PortMaster port and uses a controller-first
interface designed for the handheld's 640×480 screen.

## What the app does

### Music playback

- Plays MP3, FLAC, OGG, WAV, and M4A files through mpv.
- Browses All Songs, Albums, Artists, Folders, Favorites, Recent, and
  Playlists (`.m3u` and `.m3u8`).
- Maintains a queue with shuffle, repeat, previous, next, and automatic advance.
- Displays embedded or folder artwork and caches it locally.
- Keeps the now-playing time and progress bar updated from mpv's playback
  position, including recovery after a temporary IPC connection failure.
- Supports background playback when leaving the app with SELECT.

### Media playback

The **Media** library combines videos and pictures found in the `video` folder.
It displays thumbnails in the list and supports common formats when the
device's mpv and ffmpeg builds support them:

- Video: MP4, MKV, AVI, MOV, WebM, M4V, MPEG, and MPG.
- Pictures: JPG, JPEG, PNG, GIF, BMP, and WebP.

Video playback gives mpv exclusive display and controller ownership. The music
visualizer and music controls are not rendered underneath the video. B exits
the current video and returns to the library view.

### Visualizer and artwork processing

- Four visualizer styles: Bars, Mirror, Wave, and Radial.
- Visualizer analysis runs in the background so the interface stays usable.
- Settings can process the complete music library and show the current file,
  item count, and progress bar.
- Album art can be extracted from tags or folder images.
- Optional MusicBrainz and Cover Art Archive fetching can find missing art.

### Settings and storage

Settings is a fullscreen interface opened with **Y** from the Library. It
contains playback options, themes, accent color, library rescanning, artwork
tools, visualizer processing, independent cache controls, and storage totals
for the music library, media library, cache, and all Walkman data.

Walkman intentionally uses JSON files rather than SQLite or another database.
This keeps the port self-contained and avoids relying on additional libraries
being installed on the handheld.

## Device requirements

- Anbernic RG35XX H.
- KNULLI Linux installed and working on the device.
- PortMaster installed. Use KNULLI's PortMaster installer if it is not already
  present.
- A system Python 3 with pygame, as provided by the KNULLI/PortMaster setup.
- mpv for audio and video playback.
- ffmpeg for artwork extraction, thumbnails, and visualizer analysis.
- mutagen is optional; it improves metadata scanning when installed.
- Network access is optional and is only needed for MusicBrainz cover-art fetch.

The port does not require SQLite, a Python package download, a server, or a
computer connection after installation.

## Installation from a release ZIP

1. Download `walkman-rg35xxh.zip` from the repository's Releases page.
2. Extract the ZIP on a computer. It contains a folder named `walkman`.
3. Insert the KNULLI SD card into the computer.
4. Open the card's `roms/ports/` directory.
5. Copy the complete `walkman` folder into `roms/ports/`.
6. Safely eject the card and return it to the RG35XX H.
7. Open the KNULLI Ports menu and launch **Walkman**.
8. Copy audio files to `roms/ports/walkman/music/` and videos or pictures to
   `roms/ports/walkman/video/`.
9. Relaunch Walkman, then open **All Songs** or **Media**. The first scan may
   take a little time while metadata and thumbnails are prepared.

For an update, close Walkman and copy the new release's `walkman` folder over
the existing one. Keep the `music`, `video`, `state.json`, and `.cache`
contents; they contain your local library and preferences.

## Manual installation from source

1. Install PortMaster on KNULLI.
2. Clone or download this repository on a computer.
3. Copy the repository files into a folder named `walkman` on the SD card at
   `roms/ports/walkman/`.
4. Make sure `Walkman.sh` remains in that folder and is executable if your
   extraction tool does not preserve file permissions.
5. Add music to `music/` and other media to `video/`.
6. Launch `Walkman.sh` from the KNULLI Ports menu.

The included `gameinfo.xml` provides the PortMaster/KNULLI display metadata.
`Walkman.sh` creates the launcher thumbnail entry when needed.

## Controls

### Library and player

| Button | Action |
|---|---|
| **A** | Open, play, pause, or confirm |
| **B** | Back or cancel |
| **X** | Toggle Now Playing and details |
| **Y** | Open fullscreen Settings from the Library |
| **Up / Down** | Move through lists; change visualizer style or accent hue |
| **Left / Right** | Previous or next track on player screens |
| **R1** | Lock the screen while audio continues |
| **Hold R1** | Unlock the screen; release it before starting the unlock hold |
| **L1** | Pause or resume audio |
| **START** | Exit the app |
| **SELECT** | Exit while keeping audio playing in the background |
| **Volume buttons** | Change device volume, including while locked |

### Video

While a video is open, mpv owns the display and the controller. **B** exits the
video and returns to the originating Media or library screen. The music
visualizer and normal music transport controls are suspended during video
playback.

## Folders and generated data

The installed folder has this layout:

```text
walkman/
├── Walkman.sh
├── player.py
├── design.py
├── gameinfo.xml
├── cover.png
├── font.ttf
├── font-LICENSE.txt
├── music/
├── video/
├── state.json                 # created on first run
└── .cache/                    # created on first run
    ├── metadata/metadata.json
    ├── covers/*.png
    └── visualizer/*.viz
```

`music/` and `video/` are intentionally empty in the release package. Add
your own files; personal media is never included in source or release assets.

The cache is organized by function:

- `metadata/metadata.json` stores tags and file information.
- `covers/` stores extracted or downloaded artwork and media thumbnails.
- `visualizer/` stores precomputed visualizer data for faster playback.

Settings can clear each cache type independently. The visualizer builder can
be cancelled with **B** and will continue from valid cache files on a later
run.

## Troubleshooting

- **Walkman does not appear:** confirm the folder is exactly
  `roms/ports/walkman/` and relaunch the Ports menu.
- **No music or media appears:** check that files are in `music/` or `video/`,
  use a supported extension, and rescan from Settings.
- **A video will not play:** try an H.264/AAC MP4 or a smaller resolution.
  Playback depends on the mpv codecs and hardware acceleration available in
  the KNULLI image.
- **Video stutters:** use a lower-resolution file, close other ports, and try
  again after restarting Walkman. Hardware decoding and frame-drop are enabled
  for the RG35XX H, but some codecs remain too demanding for the device.
- **Artwork or thumbnails are missing:** allow background processing to finish,
  confirm ffmpeg is available, and use Settings to clear and rebuild covers.
- **Visualizer data is missing:** open Settings and run the full visualizer
  processor. The current file and progress are shown while it works.
- **Progress stops updating:** return to the library and reopen the track. The
  player periodically re-reads time and duration from mpv and reconnects its
  local IPC socket when needed.
- **Controls seem stuck after a video:** press B once, wait for the library to
  return, and avoid pressing transport controls during the transition.
- **Screen lock:** R1 locks only while audio is playing. Release R1, then hold
  it again to unlock. START exits the app and does not control the lock.

## Privacy and security

Walkman is a local player. It does not require an account or transmit library
data. MusicBrainz cover-art fetching is optional and sends only artist/album
search terms to the public MusicBrainz service. Local state, metadata, artwork,
visualizer data, logs, and personal media are excluded from Git and release
packages.

## License and attribution

Walkman is distributed under the [MIT License](LICENSE). The bundled DejaVu
Sans font is distributed under its own license in
[`font-LICENSE.txt`](font-LICENSE.txt); retain that file when redistributing
the port.

Walkman is an independent community project and is not affiliated with
Anbernic, KNULLI, PortMaster, or mpv.

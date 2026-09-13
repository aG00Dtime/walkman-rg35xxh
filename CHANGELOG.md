# Changelog

## [1.0.16] - 2026-09-13

- Fixed SELECT background playback getting stuck on its hand-off screen. The
  launcher now returns to KNULLI immediately while mpv clears the sleep block
  itself when playback ends.

## [1.0.15] - 2026-09-13

- Fixed KNULLI sleeping during Walkman playback. Walkman now uses KNULLI's
  battery-saver pause marker, including after SELECT sends music to background
  playback, and clears it automatically once playback ends.

## [1.0.14] - 2026-09-13

- Simplified the release archive: extract it, then copy its single `walkman`
  folder directly into `roms/ports/`.
- Keep KNULLI awake while mpv is playing, including SELECT background playback
  on systems with the standard Linux sleep inhibitor available.
- Show a clear short notice when exiting Walkman or sending music to background
  playback.

## [1.0.11] - 2026-09-12

- New generated album covers, artist pictures, and media thumbnails use compact
  JPEG files. The included `convert_cover_cache.py` tool converts old PNG
  caches safely; artist pictures are reduced to 128px to save more space.
- Both visualizer and artwork conversion tools are included in release
  packages, so existing device caches can be upgraded without rebuilding.
- Visualizer caching is lighter and faster: it streams processing instead of
  holding whole songs in memory, uses 20 smooth bars at 6 updates per second,
  and saves compact `.viz2` files.
- Settings opens immediately: the on-open storage size scan was removed.
- Removed the unnecessary **LIBRARY** dashboard label and refreshed the startup
  screen with a full cassette-themed Walkman splash.
- Fixed handheld controls: **SELECT** closes the Walkman screen while music
  keeps playing, and **START** fully exits Walkman and stops playback.
- Added the optional **Dynamic visualizer** setting. It uses a brighter, stable
  blend of the current cover-art colors across the visualizer and Now Playing
  progress bars; grayscale artwork uses the selected theme color.
- Fixed crashes from indexed-color PNG and GIF thumbnails in media and album
  lists, and fixed incorrect controller mappings.
- Added search for **All Songs**, **Media**, **Albums**, and **Artists**:
  **R2** opens the keyboard and **L2** runs the search.
- Albums and Artists use larger thumbnails. Artist photos can be fetched from
  **Settings → Fetch artist photos...** and are kept on the device.
- The final home card is **Settings**. Folder browsing lives in
  **Settings → Browse music folders**.

## [1.0.12] - 2026-09-13

- Bundle native ARM64 SQLite with the app for KNULLI Scarab on the RG35XX H.
  The library database works after copying the app folder, without installing
  a Python SQLite package or any device-side database components.
- Automatically import existing dbm/JSON metadata while keeping the originals.
  Use transactions for scan writes and retain dbm/JSON fallback on failure.
- Show the active database in Settings and include SQLite in metadata cleanup.
- Verify the bundled engine when packaging; include its build recipe,
  checksums, and attribution.
- Add configurable hardware display dimming during audio screen lock and
  restore the previous brightness after unlock or exit.
- Reduce locked-mode update work, slow volume polling, and reuse list artwork
  thumbnails to reduce CPU work and battery drain.

## [1.0.0] - 2026-09-12

Initial public release for the Anbernic RG35XX H running KNULLI.

- Added local music playback with queue, shuffle, repeat, favorites, recent
  tracks, playlists, album art, and reliable progress reporting.
- Added optional cover lookup through MusicBrainz and the Cover Art Archive.
- Added Media browsing for videos and pictures with thumbnails.
- Added fullscreen video playback through mpv with dedicated controller input,
  caching, audio synchronization, and clean B-button exit.
- Added four visualizer styles and background visualizer-cache processing.
- Added organized JSON metadata, cover, and visualizer caches.
- Added fullscreen Settings with theme, accent, library, cache, and storage
  information.
- Added background playback and R1 screen lock with L1 pause/resume.

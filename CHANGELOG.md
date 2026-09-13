# Changelog

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

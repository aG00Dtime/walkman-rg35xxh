# Contributing

Walkman is designed for a 640×480 controller-first handheld. Keep memory use,
startup time, readable text, and physical-button behavior in mind.

Before opening a pull request, run:

```powershell
python -m py_compile player.py design.py
python -m unittest discover -s tests -p 'test*.py' -v
.\package.ps1
```

Changes affecting playback should be tested on an RG35XX H running KNULLI.
Include the KNULLI version, media type, and controller buttons used when
reporting an issue. Never include personal music, media, metadata caches,
device logs, credentials, or SD-card paths in a pull request.

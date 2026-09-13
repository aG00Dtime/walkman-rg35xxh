param(
  [string]$Output = "walkman-rg35xxh.zip"
)

$ErrorActionPreference = "Stop"
python ./tools/verify_native.py
if ($LASTEXITCODE -ne 0) { throw "Bundled SQLite verification failed" }
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("walkman-rg35xxh-" + [guid]::NewGuid().ToString('N'))
$appFolder = Join-Path $stage "walkman"
New-Item -ItemType Directory -Path (Join-Path $appFolder "music") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $appFolder "video") -Force | Out-Null

$files = @(
  "Walkman.sh",
  "player.py",
  "design.py",
  "metadata_store.py",
  "native_sqlite.py",
  "convert_viz_cache.py",
  "convert_cover_cache.py",
  "gameinfo.xml",
  "README.md",
  "CHANGELOG.md",
  "LICENSE",
  "font.ttf",
  "font-LICENSE.txt",
  "cover.png"
)
foreach ($file in $files) {
  Copy-Item -LiteralPath (Join-Path "." $file) -Destination (Join-Path $appFolder $file)
}

# Keep the release simple: extracting it gives users one walkman folder to copy
# straight into roms/ports/.
Copy-Item -LiteralPath "music/.gitkeep" -Destination (Join-Path $appFolder "music/.gitkeep")
Copy-Item -LiteralPath "video/.gitkeep" -Destination (Join-Path $appFolder "video/.gitkeep")

# A Windows checkout must produce the same runnable shell script as Linux.
$launcherPath = Join-Path $appFolder "Walkman.sh"
$launcherText = [System.IO.File]::ReadAllText($launcherPath).Replace("`r`n", "`n")
[System.IO.File]::WriteAllText($launcherPath, $launcherText, [System.Text.UTF8Encoding]::new($false))

# Only ship the supported engine and its documentation, never local test builds.
$nativeFiles = @(
  "native/README.md",
  "native/SQLITE-NOTICE.txt",
  "native/linux-aarch64/build.json",
  "native/linux-aarch64/libwalkman_sqlite3.so"
)
foreach ($file in $nativeFiles) {
  $destination = Join-Path $appFolder $file
  New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
  Copy-Item -LiteralPath $file -Destination $destination
}

$outputPath = [System.IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $outputPath) {
  Remove-Item -LiteralPath $outputPath -Force
}

# Compress-Archive drops dot-files on Linux, which removes the .gitkeep files
# that preserve the empty media folders in a release ZIP. ZipFile includes them
# consistently on Windows and GitHub's Ubuntu runner.
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
  $stage,
  $outputPath,
  [System.IO.Compression.CompressionLevel]::Optimal,
  $false
)

$archive = [System.IO.Compression.ZipFile]::OpenRead($outputPath)
try {
  $entries = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/').TrimEnd('/') })
} finally {
  $archive.Dispose()
}
$required = @(
  'walkman/Walkman.sh',
  'walkman/player.py',
  'walkman/design.py',
  'walkman/metadata_store.py',
  'walkman/native_sqlite.py',
  'walkman/native/linux-aarch64/libwalkman_sqlite3.so',
  'walkman/native/linux-aarch64/build.json',
  'walkman/native/SQLITE-NOTICE.txt',
  'walkman/convert_viz_cache.py',
  'walkman/convert_cover_cache.py',
  'walkman/gameinfo.xml',
  'walkman/README.md',
  'walkman/CHANGELOG.md',
  'walkman/LICENSE',
  'walkman/font.ttf',
  'walkman/font-LICENSE.txt',
  'walkman/cover.png',
  'walkman/music/.gitkeep',
  'walkman/video/.gitkeep'
)
foreach ($item in $required) {
  if ($entries -notcontains $item) { throw "Invalid Walkman package: missing $item" }
}
Write-Output "Created $Output"

param(
  [string]$Output = "walkman-rg35xxh.zip"
)

$ErrorActionPreference = "Stop"
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("walkman-rg35xxh-" + [guid]::NewGuid().ToString('N'))
$appFolder = Join-Path $stage "walkman"
New-Item -ItemType Directory -Path (Join-Path $appFolder "music") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $appFolder "video") -Force | Out-Null

$files = @(
  "Walkman.sh",
  "player.py",
  "design.py",
  "convert_viz_cache.py",
  "convert_cover_cache.py",
  "gameinfo.xml",
  "README.md",
  "font.ttf",
  "font-LICENSE.txt",
  "cover.png"
)
foreach ($file in $files) {
  Copy-Item -LiteralPath (Join-Path "." $file) -Destination (Join-Path $appFolder $file)
}
Copy-Item -LiteralPath "music/.gitkeep" -Destination (Join-Path $appFolder "music/.gitkeep")
Copy-Item -LiteralPath "video/.gitkeep" -Destination (Join-Path $appFolder "video/.gitkeep")

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
  'walkman/convert_viz_cache.py',
  'walkman/convert_cover_cache.py',
  'walkman/gameinfo.xml',
  'walkman/README.md',
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

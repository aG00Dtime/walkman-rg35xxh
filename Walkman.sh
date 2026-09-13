#!/bin/bash
GAMEDIR="$(dirname "$0")"
XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
if [ -d "/opt/system/Tools/PortMaster/" ]; then controlfolder="/opt/system/Tools/PortMaster"
elif [ -d "/opt/tools/PortMaster/" ]; then controlfolder="/opt/tools/PortMaster"
else controlfolder="/roms/ports/PortMaster"; fi
source "$controlfolder/control.txt"
get_controls
cd "$GAMEDIR" || exit 1
export WALKMAN_MUSIC="${WALKMAN_MUSIC:-$GAMEDIR/music}"
export WALKMAN_VIDEO="${WALKMAN_VIDEO:-$GAMEDIR/video}"
GAMELIST="/$directory/ports/gamelist.xml"
PM_IMAGES="$XDG_DATA_HOME/PortMaster/config/images_pm"
if [ -f "$GAMELIST" ] && ! sed -n '/<path>\.\/walkman\/Walkman\.sh<\/path>/,/<\/game>/p' "$GAMELIST" | grep -q '<image>'; then
  sed -i '/<path>\.\/walkman\/Walkman\.sh<\/path>/,/<\/game>/ { /<name>Walkman<\/name>/a\            <image>./walkman/cover.png</image>
}' "$GAMELIST"
fi
if [ -f "$GAMEDIR/cover.png" ]; then
  mkdir -p "$PM_IMAGES"
  cp -f "$GAMEDIR/cover.png" "$PM_IMAGES/walkman.screenshot.png"
fi
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
# KNULLI's own battery-saver service watches this marker. It is the same
# mechanism used by Jellyfin RG35XX.
BATTSAVER_PAUSE="/var/run/battery-saver/walkman.pause"
WALKMAN_MPV_SOCKET="/tmp/walkman-mpv.sock"
mkdir -p "${BATTSAVER_PAUSE%/*}"
: > "$BATTSAVER_PAUSE"
cleanup() {
  # Background mpv removes this marker itself when it stops. Do not create a
  # watcher here: PortMaster must return immediately after SELECT.
  if [ ! -S "$WALKMAN_MPV_SOCKET" ]; then
    rm -f "$BATTSAVER_PAUSE"
  fi
  pm_finish 2>/dev/null || true
}
trap cleanup EXIT
pm_platform_helper "$GAMEDIR/player.py" 2>/dev/null || true
python3 ./player.py

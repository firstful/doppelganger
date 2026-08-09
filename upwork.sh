#!/usr/bin/env bash
# Unattended headed browser on an isolated virtual X display (:98).
# Uses the real logged-in profile; driven only by desktop.py (OCR + xdotool).
# No CDP, no DOM automation, no contact with the host Wayland display.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="$DIR/profiles/default"
DISP="${DISP:-:98}"
GEOM="${GEOM:-1440x900}"
URL="${1:-https://www.upwork.com/nx/find-work/best-matches}"

start_xvfb() {
  if ! DISPLAY="$DISP" xdpyinfo >/dev/null 2>&1; then
    setsid Xvfb "$DISP" -screen 0 "${GEOM}x24" -nolisten tcp </dev/null >/tmp/xvfb98.log 2>&1 &
    sleep 2
  fi
}

start_browser() {
  pkill -f "user-data-dir=$PROFILE" 2>/dev/null || true
  sleep 1
  rm -f "$PROFILE"/Singleton{,Lock,Socket,Cookie} 2>/dev/null || true
  setsid env DISPLAY="$DISP" XDG_RUNTIME_DIR=/run/user/1000 \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus KDE_FULL_SESSION=true \
    chromium --user-data-dir="$PROFILE" --ozone-platform=x11 --kiosk \
    --no-first-run --no-default-browser-check "$URL" </dev/null >/tmp/work.log 2>&1 &
}

start_xvfb
start_browser
echo "Browser launching on :$DISP -> $URL"
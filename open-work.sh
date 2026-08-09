#!/usr/bin/env bash
# Launch your logged-in profile as a native Chromium XWayland window (no CDP),
# so xdotool clicks can target it precisely.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="$DIR/profiles/default"
URL="${1:-https://www.upwork.com/nx/find-work/best-matches}"

rm -f "$PROFILE"/Singleton{,Lock,Socket,Cookie} 2>/dev/null
DISPLAY="${DISPLAY:-:1}"

# Use the larger window and stop whatever might split focus; plain headed browser.
chromium \
  --user-data-dir="$PROFILE" \
  --ozone-platform=x11 \
  --kiosk \
  --no-first-run \
  --no-default-browser-check \
  --window-size=3840,1020 \
  "$URL" 2>/dev/null
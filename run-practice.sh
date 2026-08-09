#!/usr/bin/env bash
# Practice harness: unattended OCR -> click -> verify on a known local page.
# No CDP, no DOM automation. Browser is a normal native Chromium in kiosk.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="$DIR/profiles/default"
TARGET="$DIR/practice.html"
URL="file://$TARGET"

export DISPLAY="${DISPLAY:-:1}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XAUTHORITY="${XAUTHORITY:-/run/user/1000/xauth_SATZtV}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"

step() { printf '\n==> %s\n' "$*"; }

step "0. Clean slate"
pkill -f "user-data-dir=$PROFILE" 2>/dev/null
sleep 1
rm -f "$PROFILE"/Singleton{,Lock,Socket,Cookie} 2>/dev/null

step "1. Launch native Chromium (kiosk, X11) on $TARGET"
nohup chromium --user-data-dir="$PROFILE" --ozone-platform=x11 --kiosk \
  --no-first-run --no-default-browser-check "$TARGET" >>/tmp/practice.log 2>&1 &
CHROME_PID=$!
echo "  chromium pid=$CHROME_PID"

step "2. Wait for the page to render"
for i in $(seq 1 15); do
  sleep 1
  if ! kill -0 "$CHROME_PID" 2>/dev/null; then
    echo "  ! browser exited early (see /tmp/practice.log)"
    break
  fi
done

step "3. Capture screen"
"$DIR/desktop.py" shot && echo "  captured -> $(stat -c%s "$(dirname "${DESK_SHOT:-/tmp/desk.png}")/desk.png" 2>/dev/null) bytes" || echo "  capture failed"

step "4. OCR: locate 'CLICK ME NOW'"
OUT=$("$DIR/desktop.py" find "CLICK ME NOW")
echo "  $OUT"
case "$OUT" in
  NO_MATCH|"") echo "  << WARNING: target text not found on screen";;
esac

step "5. Click it"
"$DIR/desktop.py" click "CLICK ME NOW"

step "6. Capture + OCR again to verify"
"$DIR/desktop.py" shot >/dev/null
if "$DIR/desktop.py" ocrtxt "Clicked" | grep -qi "clicked"; then
  echo "  SUCCESS: click registered and visible on screen"
else
  echo "  NO 'Clicked' text yet (maybe needs re-capture or target obscured)"
fi

printf '\n==> done. Browser left open; close it or re-run to reset.\n'
#!/usr/bin/env bash
# Launch system Chromium against the Playwright profile dir, no Playwright/CDP.
# You complete the challenge/login by hand; Chromium saves cookies to disk natively.
set -euo pipefail

STEALTH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE_MAIN="$STEALTH_DIR/profiles/default"
URL="${1:-https://www.upwork.com}"

mkdir -p "$PROFILE_MAIN"

# Wait for any stale profile lock from a previous crashed instance
if [ -f "$PROFILE_MAIN/SingletonLock" ]; then
  echo "Removing stale profile lock..."
  rm -f "$PROFILE_MAIN"/Singleton{Lock,Socket,Cookie}
fi

echo "Opening native Chromium with profile: $PROFILE_MAIN"
chromium \
  --user-data-dir="$PROFILE_MAIN" \
  --no-first-run \
  --no-default-browser-check \
  "$URL"
echo "Browser closed. Cookies are saved in the profile."
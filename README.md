# doppelganger

An indistinguishable human-like operator: cross-platform desktop + browser
automation without CDP, without DOM, without selectors. The agent sees a
screenshot, understands it via OCR + local vision ML, and interacts through
humanized mouse/keyboard input — a stand-in that behaves like the real user.

Works with any app the operator can see and click. Primary target: native
Chromium (non-CDP, anti-bot resistant) on a headless Xvfb display, driven
headedly.

## Why not CDP / Playwright / Selenium

- CDP sessions get re-challenged by Cloudflare / Forter ("Just a moment..."
  loops) because automation APIs leak through the transport.
- DOM automation requires selectors/XPath, which break constantly and are
  trivially detectable.
- This project treats the browser as a black box: screenshot in, click out.

## Layers

| Layer | Package | Responsibility |
|-------|---------|----------------|
| 1. Desktop | `desktopx` | Windows, capture, input, OCR (X11/Wayland/Win/macOS) |
| 2. Vision | `vision` | OCR rects + local ML (Florence-2): click targets, text, descriptions |
| 3. Agent | `agent` | Prompt -> intent -> perceive/match/act/verify |
| 4. Input | `desktopx.input` | Humanized mouse/keyboard at the lowest level |

## Layout

```
stealth-browser/
  desktopx/          layer 1: cross-platform desktop library (shipped)
    backends.py      X11 (xdotool), Wayland (ydotool), Windows/macOS (pyautogui)
    window.py        Window model + discovery
    capture.py       screen/window screenshots
    input.py         high-level input helpers
    ocr.py           tesseract TSV -> words, find_text, find_click
    platform.py      backend auto-detection
  vision/            layer 2: OCR + ML perception (in progress)
  agent/             layer 3: intent parsing + action loop (in progress)
  tests/             mini UI apps + end-to-end battery (in progress)
  desktop.py         standalone OCR->click CLI (reference implementation)
  upwork.sh          headed kiosk Chromium on isolated Xvfb :98
  demo.py            desktopx usage demo
```

## Quick start

```bash
# detect backend (x11 preferred; works on Xvfb)
python3 -c "from desktopx import Desktop; print(Desktop().name)"

# enumerate windows
python3 demo.py

# capture + OCR click a phrase
./desktop.py click "Find Work"          # INPUT_MODE=xdotool on :98

# headed browser on isolated display (real logged-in profile, no CDP)
./upwork.sh https://www.upwork.com/nx/find-work/best-matches
DISPLAY=:98 ./desktop.py shot && DISPLAY=:98 ./desktop.py
```

## Environment notes (Manjaro)

- Live desktop is Wayland; synthetic input on the real display is unreliable.
  Automation runs on `Xvfb :98` where `xdotool`/XTEST and `import` work.
- Chromium profile cookies are sealed by KWallet; launch with
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus` and
  `KDE_FULL_SESSION=true` (see `upwork.sh`).
- LLM gateway: `https://llm.ffilt.us` (self-signed, text-only).
- System Chromium is Arch `chromium` at `/usr/bin/chromium` (149).

## Docs

See `docs/ARCHITECTURE.md` for the full design, `docs/PLATFORMS.md` for
backend matrix, `docs/TESTING.md` for the e2e battery.

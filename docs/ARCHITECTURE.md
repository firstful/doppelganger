# Architecture Plan

The system is four layers. Each layer is a Python package under
`stealth-browser/` (project codename: **doppelganger**) with a small, stable
API. The lower layers know nothing
about the upper layers; the upper layers consume the lower ones through
plain function calls.

```
            +----------------------------+
            |        agent               |   prompt -> intent -> act -> verify
            +----------------------------+
                         |
                         v
            +----------------------------+
            |        vision              |   screenshot -> rects, text, ML targets
            +----------------------------+
                         |
                         v
            +----------------------------+
            |        desktopx            |   windows, capture, input, OCR
            +----------------------------+
                         |
                         v
            +----------------------------+
            |        backends            |   xdotool / ydotool / pyautogui
            +----------------------------+
```

## Layer 1: `desktopx` — desktop primitive

Owns the platform backends and gives every other layer a single vocabulary
of pixels and windows. No intelligence here, only faithful primitive calls.

Public surface (`desktopx/__init__.py`):

- `Desktop(display=None, backend=None)` -> driver
- `discover_windows(driver)` -> `[Window]`
- `screenshot(window=None, path=None, display=None, screen=False)` -> `(path, size)`
- `click_at(x, y, display=None, human=True)` / `move_to` / `type_text` / `scroll`
- `ocr_text(path, psm)` / `find_text(query, path)` -> `(x, y)` / `find_click`

Backend matrix (see `docs/PLATFORMS.md`):

| Backend | Linux X11 | Wayland | Windows | macOS |
|---------|-----------|---------|---------|-------|
| Enumerator | xdotool | XWayland/xdotool | win32gui | AppleScript |
| Screenshot | import | spectacle | pyautogui | screencapture |
| Mouse | xdotool | ydotool | pyautogui | pyautogui |
| Keyboard | xdotool | ydotool | pyautogui | pyautogui |
| Human moves | bezier+noise | best effort | pyautogui duration | pyautogui duration |

Key design decisions:

1. **Coordinates are absolute desktop pixels.** OCR yields offsets inside a
   window; the caller adds the window origin. `desktop.py` already does this
   via `OFFSET`.
2. **Humanization lives in the driver**, not the agent. `X11Driver.move`
   interpolates a quadratic bezier with jitter and randomized timing so every
   gesture looks organic.
3. **One capture path per backend** with a common `(path, size)` return so
   vision never needs to know which backend produced the image.

## Layer 2: `vision` — perception

Turns a screenshot into structured, clickable understanding. Two sources of
truth that must agree:

1. **OCR (tesseract)** — cheap, exact for text: word boxes
   `{left, top, w, h, conf, text}`.
2. **Local ML (Florence-2-base, transformers, CPU)** — used for:
   - classifying crops into click-target kinds (button / link / input / image)
   - dense description of the screen / regions (`<DETAILED_CAPTION>`)
   - fallback when OCR finds nothing useful

Design:

- `vision/ocr.py` — wraps tesseract TSV; returns grouped rects and text lines
  (reuses `desktopx.ocr` for raw words).
- `vision/ml.py` — lazy-loads the transformers model on first use; returns a
  singleton `Model` object so the 4-6s CPU load happens once. Exposes
  `classify_crop(pil_img) -> kind`, `describe(pil_img) -> str`.
- `vision/perceive.py` — the entry point. `perceive(screenshot_path) ->
  Perception` where `Perception` carries: full text, OCR rects, an OCR-driven
  click-target list, and (optionally) ML-described regions.

Model choice: `Florence-2-base` (Microsoft) — compact enough for CPU,
instruction-following, has `<OD>`/`<CAPTION>`/`<DETAILED_CAPTION>` tasks. No
vision in the LLM gateway, so local ML is mandatory.

Constraints:

- Torch is CPU-only; RAM is ~2.4 GB free when Chromium runs. Load the model
  lazily, keep a singleton, and prefer to run perception while the browser is
  backgrounded/closed.

## Layer 3: `agent` — prompt to action

Turns a natural-language request into a short sequence of actions and
verifies each one changed the screen.

- `agent/llm.py` — thin OpenAI-compatible client for `https://llm.ffilt.us`
  (self-signed TLS, `verify=False`, no proxy, model `auto`). Structured,
  one-shot intent extraction with a strict JSON schema.
- `agent/intents.py` — maps `(action, target, value)` tuples to concrete
  `desktopx` calls with fuzzy text matching against OCR rects; falls back to
  typed-URL navigation and keyboard shortcuts when OCR fails.
- `agent/agent.py` — the loop:

```
loop:
  screenshot -> perceive()          # OCR rects + text + ML targets
  if intent.target matches a rect:  # fuzzy match, best confidence
      humanized click / type / scroll
      sleep -> screenshot           # verify the screen changed
      continue / done
  else:
      fallback: navigate via Ctrl+L, keyboard-only path
```

Scope for v1 (explicit): `click`, `type`, `scroll`, `navigate`, `verify`.
Explicitly out of scope: multi-goal planning, chains of intent, any
DOM/session access.

## Layer 4: input humanization

Already implemented inside `desktopx.backends` (`X11Driver.move`). Rules:

- bezier path, not straight lines
- jitter ±1.5 px per step, 12-18 steps, 8-30 ms sleep
- randomized pre-click pause
- typed text at randomized per-char delay

Rationale: bot-detection and human-factors software both flag teleporting
cursors and instant keystrokes. Making the *input* look human is the base
layer; OCR+ML perception is what lets the agent aim it.

## Browser strategy (non-CDP)

`upwork.sh` launches native Chromium with the real logged-in profile on an
isolated `Xvfb :98`:

- `--ozone-platform=x11 --kiosk` headed browser on the virtual display
- `DBUS_SESSION_BUS_ADDRESS` + `KDE_FULL_SESSION=true` so KWallet unseals
  profile cookies
- no CDP flags, no Playwright, no automation APIs — only screenshots and
  XTEST/xdotool input

Navigation is done like a human: `Ctrl+L` focus the address bar, type URL,
Enter. All clicks/typing flow through `desktopx` humanized input.

## Testing strategy

See `docs/TESTING.md`. Core idea: deterministic mini UI apps
(`tests/apps/*.html`) served locally, launched in the kiosk browser on
`:98`, then exercised end-to-end by the agent. Each test asserts the visible
screen changed as expected (OCR-verifiable), e.g. a "Clicked" counter.

## Anti-goals

- No CDP, no DevTools protocol, no automation-flagged Chromium.
- No DOM selectors, XPath, or page object models.
- No reliance on the LLM for vision.
- No synthetic input on the live Wayland desktop (unreliable) — always on an
  isolated X display.

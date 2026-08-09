# Testing Strategy

Goal: prove the full stack (browser -> OCR/vision -> humanized input) with
deterministic, self-contained tests. No live external sites; no CDP.

## Approach

1. **Mini UI apps** in `tests/apps/` — small HTML pages that expose
   OCR-verifiable state (buttons that change a visible counter, forms,
   navigation links).
2. **Serve locally** (`python3 -m http.server`) and open in the kiosk
   Chromium on the isolated Xvfb display `:98` (see `upwork.sh`).
3. **Drive end-to-end** through the real `agent` + `vision` + `desktopx`
   stack on `:98` — screenshots only, XTEST input only.
4. **Assert on visible state** — each step re-OCRs the screen and checks the
   expected text/state appeared or changed.

## App fixtures (planned)

| App | Purpose |
|-----|---------|
| `login.html` | type into username/password fields, click submit, see welcome |
| `dashboard.html` | click nav items, verify heading swaps |
| `counter.html` | click button N times, verify counter text |
| `scroll.html` | scroll feed, verify new content visible |

## Test runner (`tests/run_tests.py`)

```
for each app fixture:
    launch kiosk browser on :98 -> app URL
    run scenario:
        perceive()                     # OCR + ML
        agent.do("click Sign In")      # fuzzy match -> human click
        assert_visible("Welcome")      # re-OCR the screen
    cleanup browser
```

Pass criteria:

- clicks land on the intended element (verified by state change, not just
  coordinates)
- typed text appears in fields (verified by OCR of field contents)
- scroll reveals new content
- full loop survives ~10 iterations without a mismatch

## Isolation

- All tests run on `Xvfb :98`; the live Wayland desktop is never touched.
- Each run restarts Chromium with a fresh test profile (`--user-data-dir`)
  so state never leaks between scenarios.
- Screenshots land in `/tmp/` and are cleaned up.

## Running

```bash
./tests/run_tests.py           # runs the full battery on :98
./tests/run_tests.py --app login   # single fixture
```

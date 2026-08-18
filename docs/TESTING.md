# Testing Strategy

Goal: prove the full stack (browser -> OCR/vision -> humanized input) with
deterministic, self-contained tests. No live external sites; no CDP.

## Display resolution is load-bearing

Automation runs on `Xvfb :98` at **3840x2160 (4K) with Chromium
`--force-device-scale-factor=2.0`** (200%; 1920x1080 logical CSS). Small
UI text — especially prices with raised superscript cents — only has enough
physical pixels for OCR when rendered at real 2x, not when upscaled by
LANCZOS interpolation (which blurs glyph edges and defeats tesseract's
binarizers). The fixtures and price recovery assume 4K@200% for the pixel
budget.

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

## App fixtures

Realistic-density mini apps — colored buttons, badges, tables, sidebars —
so OCR tuning generalizes instead of overfitting to toy pages. Each app
injects a `READY` marker after its JS handlers bind; tests wait for it
before acting (a painted page is not an interactive page).

| App | Purpose |
|-----|---------|
| `counter.html` | Warehouse counter: blue "Add Unit" button (white-on-color OCR), live counter + history line |
| `login.html` | Corporate login: blue submit button, labels focusing inputs via `for`, welcome/error states as form feedback |
| `dashboard.html` | Payments dashboard: sidebar nav, dark header with red LIVE badge, stat cards, invoice table |
| `scroll.html` | Operator log feed: severity badges (green INFO / orange WARN / red ERROR — three hue cohorts), wheel-scroll to tail |
| `prices.html` | Hardware product grid: superscript-cents prices ($12.98 rendered as big "12" + raised "98"), bulk tiers, model numbers that must NOT be misread as prices |

## Test runner (`tests/run_tests.py`)

```python
for each app fixture:
    launch kiosk browser on :98 -> app URL  (wait for READY marker)
    perceive()                              # OCR (+ price recovery)
    dispatch(Intent)                        # click / type / scroll
    re-perceive and assert on visible state change
```

Run modes:

```bash
./tests/run_tests.py                 # full battery
./tests/run_tests.py --app prices    # single fixture
./tests/run_tests.py --with-llm      # also run one full agent.do() LLM loop
```

Pass criteria:

- clicks land on the intended element (verified by state change, not just
  coordinates) — target matching is word-window-aware, so a nav bar like
  "Home Settings Reports" clicks the exact word, not the row center
- typed text appears in fields (verified by OCR of field contents)
- colored UI text (white on blue buttons, orange/red badge labels) is read
  via a 3-pass OCR merge: grayscale + color + saturation-mask inverse
- prices with superscript cents are recovered to "$12.98" (not "1298"),
  and model numbers are never misread as prices
- scroll reveals new content
- full loop survives repeated runs without a mismatch (2 consecutive clean
  runs required before committing)

## Isolation

- Tests run on `Xvfb :98`; the live Wayland desktop is never touched.
- **Single persistent profile** (`profiles/default`) is used for fixtures
  AND real sites — a site sees a browser with real cookies/history, not a
  fresh bot. Override via `DOP_PROFILE`. This is what keeps anti-bot pages
  (HD, etc.) from soft-blocking the search endpoint.
- The runner kills any stray kiosk browser before launching (a leftover
  steals clicks from the new one).
- Screenshots land in `/tmp/dop-tests/`.

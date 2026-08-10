# vision — Layer 2 spec

Turns a screenshot into structured, clickable understanding. Two sources of
truth that must agree: tesseract OCR (cheap, exact for text) and local ML
(Florence-2-base, CPU) for click-target kinds and descriptions.

## API

```
perceive(path) -> Perception
```

`Perception` fields:

- `path`          — source image path
- `text`          — full OCR text, whitespace-collapsed
- `words`         — raw OCR boxes: `[{left, top, w, h, conf, text}]`
- `lines`         — OCR boxes grouped into text lines:
                   `[{box: {left, top, w, h}, text, conf}]`
- `targets`       — clickable rects:
                   `[{kind, box, text, conf, source}]` where
                   `kind` in `{button, link, input, image, unknown}`,
                   `source` in `{"ocr", "ml"}`
- `description`   — ML dense caption of the whole screen (str, optional)
- `error`         — if ML is unavailable, contains the reason; targets still
                   populated from OCR alone.

## Modules

### vision/ocr.py
- `ocr_words(path, psm="11") -> [word]` — thin wrapper over tesseract TSV
  (reuses desktopx.ocr internals if importable, else direct subprocess).
- `group_lines(words) -> [line]` — merge words sharing a baseline/height into
  lines (top within ±8px, overlapping x-ranges).

### vision/ml.py
- singleton `get_model() -> Model | None` — lazy-loads transformers +
  Florence-2-base on first call; returns None (logs reason) if deps/weights
  missing. Keeps process RAM capped by unloading on `release()`.
- `Model.kind(crop_pil, text="") -> str` — classify crop into
  button/link/input/image/unknown via `<OCR>` + prompt; fallback "unknown".
- `Model.describe(pil) -> str` — `<DETAILED_CAPTION>`.
- `Model.release()` — free weights (gc + `torch.cuda.empty_cache` noop on
  CPU; used to hand RAM back before heavy browser runs).

### vision/perceive.py
- `perceive(path, with_ml=True) -> Perception` — runs OCR, groups lines,
  builds OCR-derived targets (heuristics: short text in a box, position on
  screen), optionally enriches with ML kinds + caption.
- `load_image(path) -> PIL.Image` — RGB convert, used by all modules.

## Design rules

1. OCR is never optional; ML is best-effort. The agent must be able to act
   on OCR-only perception when RAM is tight.
2. Rect coordinates are absolute desktop pixels (caller applies window
   offset, matching desktopx).
3. `ml.get_model()` never raises — returns None + sets `Perception.error`.
4. ML kind classification batches: many small crops in one forward pass.

## Dependencies
- system: `tesseract`, PIL
- optional: `torch`, `transformers`, Florence-2-base weights
  (auto-downloaded on first use; offline flag falls back to OCR-only).

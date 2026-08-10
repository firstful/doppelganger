# agent — Layer 3 spec

Turns a natural-language request into concrete desktop actions and verifies
each one changed the screen. Loop only: perceive -> match -> act -> verify.

## API

```
Agent(llm=None, display=None)   # llm defaults to LLM(verify=False)
agent.do(prompt, timeout_s=60) -> StepReport
```

`StepReport`:
- `prompt`        — original request
- `steps`         — `[StepReport]` of sub-steps if multi-step
- `ok`            — bool, verified screen change matched expectation
- `summary`       — human-readable narration
- `actions`       — actions actually dispatched `[{action, target, x, y}]`

## Modules

### agent/llm.py
- `LLM(base="https://llm.ffilt.us", model="auto", verify=False)` — minimal
  OpenAI-compatible chat client (no external SDK).
- `LLM.complete(system, user, json=False, timeout=120) -> str|dict`
  - posts to `{base}/v1/chat/completions` with `requests` (verify=False,
    no proxy). Returns content string; if `json=True`, returns parsed dict.
- `LLM.extract_intent(prompt) -> Intent` — one-shot: returns JSON
  `{action, target, value, fallback}`. `action` in
  `{click, type, scroll, navigate, verify, done}`; `target` = on-screen text
  to match; `value` = text to type / scroll delta; `fallback` = a URL or
  key-combo string. On any failure returns a safe no-op `Intent`.

### agent/intents.py
- `Intent(action, target, value, fallback)` dataclass.
- `match_target(perception, text) -> rect|None` — fuzzy word-sequence match
  against OCR lines (case-insensitive, substring + per-word distance),
  returns the best-scoring line box; None if no reasonable match.
- `dispatch(intent, perception, desktop, human=True) -> action_log` — maps an
  Intent to concrete `desktopx` calls:
  - click  -> `find_click`/click center of matched rect
  - type   -> click input rect (or `fallback` focus key) then `type_text`
  - scroll -> `scroll(delta)` at pointer
  - navigate -> `Ctrl+L`, type `fallback` URL, Enter
  - verify -> screenshot + OCR, returns bool
  - done   -> no-op, returns True
- `fuzzy_match(needle, haystack) -> float` — token-overlap similarity in
  [0,1], used by `match_target` and by agent verify narration.

### agent/agent.py
- `agent.do(prompt)`:
  1. `LLM.extract_intent(prompt)` -> Intent
  2. screenshot current window -> `perceive()`
  3. `match_target` against perception (if action needs a target)
  4. `dispatch(intent, ...)` with humanized input
  5. sleep ~300ms, screenshot again, OCR; if action was verify, compare
  6. return `StepReport` with ok = verified state change (or user-specified
     target visible)

## Design rules

1. The LLM is a brain only — it never touches the screen. All perception is
   OCR/ML, all action is desktopx input.
2. Failure is graceful: every step degrades to OCR-only matching and the LLM
   falls back to a no-op instead of hallucinating coordinates.
3. Humanization is at the driver level; the agent never crafts raw input.
4. `verify` compares OCR text before/after; a changed screen is success.

## Scope (v1)
- actions: click, type, scroll, navigate, verify, done
- single-step prompts (one Intent). Multi-goal planning is a later layer.
- target matching by on-screen text only (no layout/ARIA access).

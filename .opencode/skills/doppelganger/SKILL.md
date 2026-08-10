---
name: doppelganger
description: Use when working on the doppelganger project (this repo): building or testing the 4-layer OCR+ML vision desktop/browser automation stack (desktopx, vision, agent, tests), running the agent against native Chromium on the isolated Xvfb :98 display, using the llm.ffilt.us gateway, or pushing to the gitea.ffilt.us repo. Covers the no-CDP / no-selector / humanized-input constraints, the vision package APIs, and the Gitea credential/SSL setup.
---

# doppelganger — human-like desktop/browser automation

This repo builds a 4-layer automation stack that operates apps as a black box:
screenshot in, humanized mouse/keyboard out. **No CDP, no DOM selectors, no
XPath, no careful prompting.** Primary target: native Chromium (anti-bot
resistant, headed) on an isolated Xvfb display, driven unattended.

## Layers

| Layer | Package | Responsibility |
|-------|---------|----------------|
| 1 Desktop | `desktopx` | windows, capture, input, OCR — X11 (xdotool) / Wayland (ydotool) / Win / macOS (pyautogui) |
| 2 Vision | `vision` | tesseract OCR rects + local ML (Florence-2-base) click-targets & captions |
| 3 Agent | `agent` | prompt → LLM intent → fuzzy target match → humanized act → OCR verify |
| 4 Input | `desktopx.input`/backends | quadratic-bezier human cursor, jittered typing |

## Constraints (always honor)

1. Never use CDP/Playwright/devtools — sessions get re-challenged by
   Cloudflare/Forter.
2. Never inject selectors/XPath; perception is screenshots only.
3. Automate on `Xvfb :98`, never the live Wayland desktop (synthetic input is
   unreliable there). Coordinate system: absolute desktop pixels.
4. Vision ML is best-effort: perception must work OCR-only when RAM is tight
   or weights are missing. `vision.ml.get_model()` never raises.
5. Humanization lives in the drivers (`X11Driver.move`, bezier + jitter), not
   in the agent.

## Environment facts (Manjaro)

- LLM gateway: `https://llm.ffilt.us` — OpenAI-compatible, self-signed TLS
  (curl/git need `-k` / `sslVerify false`), model `auto`. Text-only, no vision.
- Gitea: web on `http://192.168.1.2:3000`, HTTPS API at
  `https://gitea.ffilt.us/api/v1` (self-signed). Repo: `reeds/doppelganger`.
  Git auth is handled by the global credential helper that reads
  `GITEA_USER`/`GITEA_TOKEN` from the environment (see below).
- Headed browser launch: `./upwork.sh [URL]` — kiosk Chromium on `:98` with
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus` +
  `KDE_FULL_SESSION=true` (KWallet unseals the profile cookies in
  `profiles/default`).
- Reference CLI: `./desktop.py` (capture/ocr/find/click/clickat/type/scroll).

## Vision API

```python
from vision import perceive
p = perceive("/tmp/shot.png", with_ml=True)   # with_ml=False for OCR-only
p.text                      # full OCR text
p.lines                     # [Line] with .box (absolute px), .text, .conf
p.find_line("Submit Button")  # fuzzy best line or None
p.target_for("login")         # click Target or None
p.targets                   # clickable rects [{kind, box, text, conf, source}]
p.as_dict()                 # serializable
from vision.ml import get_model, release
get_model()                 # lazy Florence-2 singleton or None; release() frees RAM
```

Line grouping: same baseline (`y_tol=8`) + horizontal gap `<= gap_tol=160`.

## Agent API

```python
from agent import Agent, LLM, match_target, dispatch
a = Agent()                     # llm defaults to LLM() -> https://llm.ffilt.us, model auto
report = a.do("click the Sign In button")
report.ok, report.summary, report.actions, report.intent
```

- `LLM.complete(system, user, json_mode=True)` / `LLM.extract_intent(prompt)`
  → `Intent(action, target, value, fallback)`; action ∈ click/type/scroll/
  navigate/verify/done. Failures degrade to `done` (no-op) — never hallucinate
  coordinates.
- `match_target(perception, text)` — token-overlap similarity (order/substring
  aware, min token length 4; length penalty only when the line is shorter than
  the needle). Returns best Line or None.
- `dispatch(intent, perception, desktop, human=True)` → action-log dict.
- Agent loop: perceive → match → act → verify (re-OCR, screen must change).

## Test workflow (e2e on :98)

1. Build a mini UI fixture in `tests/apps/` (plain HTML with OCR-verifiable
   state: counters, forms, nav).
2. Serve it locally (`python3 -m http.server`), launch in kiosk Chromium on
   `:98` with a fresh `--user-data-dir` test profile.
3. Drive through the real stack only (screenshots + XTEST input).
4. Assert on re-OCR of the visible screen; see `docs/TESTING.md`.

## Pushing to Gitea (doppelganger repo)

```bash
source ~/.bashrc               # exports GITEA_URL, GITEA_USER, GITEA_TOKEN
cd /home/reeds/stealth-browser
git remote -v                  # origin/gitea -> https://gitea.ffilt.us/reeds/doppelganger.git
git add -A && git commit -m "..." && git push gitea main
```

Auth: the global git config sets
`credential.https://gitea.ffilt.us.helper` to a script that echoes
`GITEA_USER`/`GITEA_TOKEN` from the environment, and
`http.https://gitea.ffilt.us/.sslVerify=false` for the self-signed cert. The
token must NOT be embedded in the remote URL. To create the repo via API:

```bash
curl -sk -X POST -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"doppelganger","private":false}' \
  https://gitea.ffilt.us/api/v1/user/repos
```

The token needs `write:user` scope to create repos; the `read:...`/`write:repository`
token cannot create repos via API (push-to-create is disabled for users).

## Docs

- `docs/ARCHITECTURE.md` — 4-layer design
- `docs/PLATFORMS.md` — backend matrix + gotchas
- `docs/TESTING.md` — e2e battery plan
- `docs/SPEC-VISION.md`, `docs/SPEC-AGENT.md` — layer specs

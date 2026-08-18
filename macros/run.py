"""Deterministic macro player — NO LLM, NO CDP.

Replays a recorded .macro.json against the live screen. Each step is pure
data: OCR the current screen, resolve the stored anchored fraction to a
click target, dispatch the raw input action, and optionally verify the next
step's anchor appeared before moving on. Fully repeatable: given the same
app state it produces the same actions every run, independent of any model.

The player is intentionally dumb/brittle in one sense — it does what the
recording says, retrying only to wait out async UI. Intelligence lives at
record time (picking good anchors) and in the app (stable, OCR-readable
labels). This is the "an agent doesn't have to drive every step" property:
capture once, replay forever.

Usage:
    python -m macros.run path.macro.json --display :98
"""

import argparse
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from desktopx import Desktop  # noqa: E402
from vision.perceive import perceive  # noqa: E402
from . import steps as S  # noqa: E402
from .resolve import resolve_step, UnresolvedTarget  # noqa: E402


class MacroPlayer:
    """Replay engine bound to one display + macro doc."""

    def __init__(self, doc, display=None, shot_dir="/tmp", human=True,
                 verify=True, anchor_timeout=12.0, backend=None):
        self.doc = doc
        self.display = display
        self.shot_dir = shot_dir
        self.human = human
        self.verify = verify
        self.anchor_timeout = anchor_timeout
        self.backend = backend
        self.desktop = Desktop(display=display, backend=backend)
        self.steps = doc["steps"]
        self.actions = []   # log of resolved, dispatched actions
        self._n = 0

    # -- perception -------------------------------------------------------
    def _capture(self, name=None):
        name = name or f"macro_{self._n}"
        p = f"{self.shot_dir}/{name}.png"
        # Capture via the bound driver (self.desktop.screenshot) — never the
        # module-level screenshot() which re-detects the backend and can
        # pick Wayland when WAYLAND_DISPLAY leaks into the env (its
        # screenshot rejects the screen= kwarg). X11 driver takes screen=True
        # to grab the root window.
        if getattr(self.desktop, "name", "") == "x11":
            self.desktop.screenshot(None, p, screen=True)
        else:
            self.desktop.screenshot(None, p)
        return p

    def _perceive(self, name=None):
        return perceive(self._capture(name), with_ml=False)

    def _viewport(self):
        try:
            return self.desktop.root_size()
        except Exception:
            p = self._perceive()
            return {"width": p.width, "height": p.height}

    # -- resolution with retry --------------------------------------------
    def _wait_target(self, step, perception, iterations=8, interval=0.6):
        """If the step names a `target` text, wait until it's visible so we
        click the real control; else wait for the anchor. Re-OCR until the
        locating text is found, or fall back to the stored fraction."""
        per = perception
        txt = step.get("target") or step.get("anchor", "")
        for _ in range(iterations):
            try:
                x, y = resolve_step(step, per, viewport=self._viewport())
                return x, y, per
            except UnresolvedTarget:
                time.sleep(interval)
                per = self._perceive(f"await_{txt}")
        raise UnresolvedTarget(
            f"{txt!r} never became visible "
            f"(waited {iterations * interval:.1f}s)")

    # -- step dispatch ------------------------------------------------------
    def play_step(self, step):
        self._n += 1
        action = step["action"]
        drv = self.desktop  # bound driver (forced to X11 for Xvfb targets)

        if action == "wait":
            time.sleep(float(step.get("seconds", 0.5)))
            return {"action": "wait", "ok": True}

        if action == "scroll":
            lines = int(step.get("lines", 4))
            direction = step.get("direction", "down")
            delta = -lines if direction.startswith("up") else lines
            drv.scroll(delta)
            time.sleep(0.2)
            return {"action": "scroll", "ok": True, "detail": direction}

        if action == "key":
            drv.press(step["combo"])
            time.sleep(0.2)
            return {"action": "key", "ok": True, "detail": step["combo"]}

        if action not in ("click", "type"):
            return {"action": action, "ok": False,
                    "detail": f"unknown action {action}"}

        # click/type: resolve against current OCR, waiting for the anchor.
        per = self._perceive("pre")
        x, y, _ = self._wait_target(step, per)
        drv.click(x, y, human=self.human)
        log = {"action": action, "anchor": step.get("anchor", ""),
               "x": x, "y": y, "ok": True, "detail": f"clicked @ {x},{y}"}
        if action == "type":
            time.sleep(0.2)
            drv.type(step["text"])
            log["detail"] += f" typed {step['text']!r}"
            log["value"] = step["text"]
        return log

    # -- full run -----------------------------------------------------------
    def run(self, verify_landmarks=True):
        self.actions = []
        for step in self.steps:
            a = self.play_step(step)
            self.actions.append(a)
            if verify_landmarks and not a["ok"]:
                raise RuntimeError(f"step {self._n} failed: {a['detail']}")
        return self.actions


def _load(path):
    return S.load(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("macro", help="path to .macro.json")
    ap.add_argument("--display", default=os.environ.get("DISPLAY", ":0"))
    ap.add_argument("--no-verify", action="store_true",
                    help="skip per-step anchor waiting")
    ap.add_argument("--no-human", action="store_true",
                    help="teleport the cursor instead of human motion")
    args = ap.parse_args()

    doc = _load(args.macro)
    print(f"replaying {args.macro} ({len(doc['steps'])} steps)")
    print(S.pretty(doc["steps"]))
    player = MacroPlayer(doc, display=args.display, human=not args.no_human,
                         backend="x11")
    try:
        player.run()
        print("\nmacro completed OK")
    except Exception as e:
        print(f"\nmacro FAILED at step {player._n}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

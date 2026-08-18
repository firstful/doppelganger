"""Resolve a macro step's stored relative coords to live screen pixels.

Scale-invariance core: a click is stored as a fraction (fx, fy) of a text
anchor's box. At replay we OCR the current screen, locate the anchor text,
and multiply the fraction by the anchor's CURRENT box dimensions. Whatever
resolution / device-scale-factor the browser now runs at, the fraction
lands on the same logical spot inside that control.

If the anchor text is absent from the current screen we do NOT fall through
to a stale guess: we report the step as unresolved so the player can retry,
wait, or fail loudly. `screen` mode resolves against the live viewport.
"""

import time

from agent.intents import match_target


class UnresolvedTarget(Exception):
    """Raised when a macro step's anchor text can't be found on screen."""


def resolve_step(step, perception, viewport=None, min_sim=0.55):
    """Return (x, y) screen pixels for an interactive step, or raise.

    Resolution priority (most scale-invariant first):
      1. target : the step's `target` is OCR text identifying the exact
                  control. Locating it re-finds the control wherever it is,
                  so clicking its center is invariant to resolution, layout
                  and reflow — no fraction needed.
      2. anchor : the step's stored (fx, fy) fractions of the anchor box.
                  Scale-invariant when the layout scales proportionally.
      3. screen : pure viewport fraction.

    Falls back anchor<-target and screen<-anchor so a macro recorded with
    rich anchors still replays if a target's text changes or vanishes.
    """
    action = step["action"]
    if action not in ("click", "type"):
        raise ValueError(f"step {action} has no coordinate target")

    # 1) Preferred: locate the exact identifying text, click its center.
    target = step.get("target")
    if target:
        ln = match_target(perception, target, min_sim=min_sim)
        if ln is not None:
            return ln.box.cx, ln.box.cy

    # 2/3) Fall back to stored anchored / screen fractions.
    mode = step.get("mode", "anchor")
    ry, rx = float(step["fy"]), float(step["fx"])

    if mode == "screen":
        if not viewport or not viewport.get("width"):
            raise UnresolvedTarget("screen-mode step needs live viewport")
        W = max(viewport["width"], 1)
        H = max(viewport["height"], 1)
        return int(rx * W), int(ry * H)

    anchor = step.get("anchor", "")
    ln = match_target(perception, anchor, min_sim=min_sim)
    if ln is None:
        raise UnresolvedTarget(
            f"anchor {anchor!r} not found on current screen")
    a = ln.box
    x = int(a.left + rx * a.width)
    y = int(a.top + ry * a.height)
    return x, y


def wait_for(pred, timeout_s=12, interval=0.5, desc="target"):
    """Poll `pred()` until truthy or timeout. Used to await async UI steps."""
    end = time.time() + timeout_s
    last = None
    while time.time() < end:
        try:
            v = pred()
        except Exception as e:  # perception/OCR may throw transiently
            last = e
            v = False
        if v:
            return True
        last = v
        time.sleep(interval)
    raise TimeoutError(f"timed out waiting for {desc} (last={last!r})")

"""Macro data model: recordable, OCR-anchored, scale-invariant steps.

A macro is a JSON-serializable list of Step dicts. Coordinates are NEVER
stored as absolute pixels. Each interactive step stores where it clicked as
a fraction of a *recognized text anchor's* bounding box, so replay works at
any resolution / device scale factor:

    x = anchor.box.left + round(fx * anchor.box.width)
    y = anchor.box.top  + round(fy * anchor.box.height)

where (fx, fy) are in [0,1] relative to the anchor box. Two coordinate
modes:

  anchor  -> relative to the box of OCR text `anchor` (best: layout- and
             scale-invariant; survives resolution AND reflow of everything
             outside the anchor).
  screen  -> relative to the full viewport (W, H) at record time:
             scale-invariant to resolution changes, but NOT to layout
             reflow. Used only when no text anchor is near the target.
  offset  -> anchor plus a fixed relative offset, for clicking near-but-
             not-on an anchor (e.g. an input field next to its label): the
             click lands at (ax + fx*w_a, ay + fy*h_a) where a is the
             anchor box. fx/fy may leave [0,1] for offset mode.

Storing fx/fy as *fractions of the anchor box* (not of the screen) is what
keeps a click tied to its control when the whole page reflows or the
browser rescales. Screen mode divides by the recorded (W, H) at capture so
replay at a bigger display still lands on the same relative spot.
"""

import json
import time

# Action vocabulary (opaque to the app — no DOM).
VALID_ACTIONS = {"click", "type", "scroll", "key", "wait"}


# --------------------------------------------------------------------------
# Step construction helpers
# --------------------------------------------------------------------------

def click_step(anchor, fx, fy, note="", mode="anchor", target=None):
    """anchor+fraction archives the click; `target` (optional) is OCR text
    that, when locatable, is clicked at its center at replay — the most
    scale-invariant path, since OCR re-finds the exact control anywhere on
    screen. `anchor`+`fx`/`fy` are the fallback when `target` isn't found
    (e.g. it changed), and record where the click was for diagnostics."""
    s = {"action": "click", "mode": mode, "anchor": anchor,
         "fx": fx, "fy": fy, "note": note}
    if target:
        s["target"] = target
    return s


def type_step(anchor, fx, fy, text, note="", mode="anchor", target=None):
    s = click_step(anchor, fx, fy, note=note, mode=mode, target=target)
    s["action"] = "type"
    s["text"] = text
    return s


def scroll_step(lines=4, direction="down"):
    return {"action": "scroll", "lines": lines, "direction": direction}


def key_step(combo, note=""):
    return {"action": "key", "combo": combo, "note": note}


def wait_step(seconds=0.5):
    return {"action": "wait", "seconds": seconds}


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------

def dump(steps, path, viewport=None, **meta):
    """Write a macro to `path` as JSON.

    viewport: optional (W, H) dict captured at record time. Stored so a
    screen-mode step can record absolute coords and replay resolves them to
    the same relative fraction.
    """
    doc = {"meta": {"created": time.time(), "viewport": viewport, **meta},
           "steps": steps}
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    return path


def load(path):
    with open(path) as f:
        doc = json.load(f)
    return doc


def pretty(steps):
    out = []
    for i, s in enumerate(steps):
        a = s["action"]
        anchor = s.get("anchor", "")
        if a in ("click", "type"):
            out.append(f"{i:2} {a:6} @ {anchor!r} "
                       f"({s['fx']:.3f},{s['fy']:.3f})"
                       + (f" text={s['text']!r}" if a == "type" else ""))
        elif a == "scroll":
            out.append(f"{i:2} {a:6} {s['direction']} {s['lines']}")
        elif a == "key":
            out.append(f"{i:2} {a:6} {s['combo']}")
        elif a == "wait":
            out.append(f"{i:2} {a:6} {s['seconds']}s")
    return "\n".join(out)

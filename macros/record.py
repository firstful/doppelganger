"""Interactive macro recorder: perform a task once, capture it as anchors.

A human (or a one-off agent pass) drives the app naturally. For each click
we OCR the current screen, snap the click to the *nearest* recognized text
line, and store it as an anchor + relative fraction rather than raw pixels
— so the recorded macro replays at any resolution.

Two recording modes:
  interactive (default): a small prompt loop. You move the mouse to where
      you'd click and press Enter; the recorder reads the current pointer
      location, OCRs the screen, and snaps the click to the nearest line.
      Then it asks what to type (skip = plain click), then whether the UI
      changed (add a wait) or we keep recording.
  scripted: pass a list of (x, y, value?) tuples and it records them in
      order, snapshotting+OCR-ing the screen before each one.

The output .macro.json is pure data — the agent never drives replay.
"""

import argparse
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from desktopx import Desktop  # noqa: E402
from desktopx.capture import screenshot  # noqa: E402
from vision.perceive import perceive  # noqa: E402
from . import steps  # noqa: E402


def _box_of_click(perception, x, y):
    """Snap a click to the nearest OCR line; return (Line, fx, fy).

    fx, fy are the click position as a fraction of that line's box, so
    replay recomputes pixels from the box. Prefer a line whose box actually
    CONTAINS the point; otherwise the nearest line center (tolerated when
    clicking a control adjacent to its label).
    """
    best_contain = None
    best_contain_d = float("inf")
    best_near = None
    best_near_d = float("inf")
    for ln in perception.lines:
        b = ln.box
        cx = b.left + b.width / 2
        cy = b.top + b.height / 2
        d = max(abs(cx - x), abs(cy - y))
        if b.left <= x <= b.right and b.top <= y <= b.bottom:
            if d < best_contain_d:
                best_contain_d = d
                best_contain = ln
        elif d < best_near_d:
            best_near_d = d
            best_near = ln
    ln = best_contain or best_near
    if ln is None:
        return None, None, None
    b = ln.box
    fx = (x - b.left) / max(b.width, 1)
    fy = (y - b.top) / max(b.height, 1)
    return ln, fx, fy


def anchor_click(perception, anchor_text, x, y, min_sim=0.6):
    """Record a click anchored to a SPECIFIC stable label/word box.

    `anchor_text` is a stable, always-visible OCR token (a label or one of
    its words, e.g. "Shipper name" or "Shipper"). The click at (x, y) is
    stored as (fx, fy) relative to the matched box. fx/fy may exceed [0,1]
    (offset mode): replay lands at (box.left + fx*w, box.top + fy*h).
    Anchoring to a stable token — not a mutable placeholder — keeps the step
    replayable after the field's content changes. For a vertical form
    (label above input) anchor to the label; fy > 1 points down into the
    field.
    """
    from agent.intents import match_target

    ln = match_target(perception, anchor_text, min_sim=min_sim)
    if ln is None:
        return None
    b = ln.box
    fx = (x - b.left) / max(b.width, 1)
    fy = (y - b.top) / max(b.height, 1)
    return ln.text, round(fx, 4), round(fy, 4)


def locate_field_below(perception, anchor_box, max_dy=300):
    """Return the (cx, cy) center of the input field BELOW an anchor label.

    For a vertical form (label on its own row, input under it): find the
    OCR-visible words sitting below the label in roughly the same horizontal
    band (the input's placeholder), return their cluster center. Used only
    at record time; replay uses the stored offset fraction.
    """
    ab = anchor_box
    cands = []
    for w in perception.words:
        b = w.box
        if b.top < ab.bottom - 4:
            continue                      # not below the label
        if b.top - ab.bottom > max_dy:
            continue                      # too far down (next field)
        # horizontal overlap with the label's span (generous — inputs are
        # wider than their labels, so extend right, allow small left drift)
        if b.right < ab.left - 40 or b.left > ab.right + 220:
            continue
        cands.append(b)
    if not cands:
        return None
    # Cluster horizontally; keep the run nearest the label row below.
    cands.sort(key=lambda b: b.left)
    runs = []
    cur = [cands[0]]
    for b in cands[1:]:
        if b.left - cur[-1].right <= 200:
            cur.append(b)
        else:
            runs.append(cur)
            cur = [b]
    runs.append(cur)
    runs.sort(key=lambda r: max(abs(b.cy - ab.bottom) for b in r))
    run = runs[0]
    cx = int(sum(b.cx for b in run) / len(run))
    cy = int(sum(b.cy for b in run) / len(run))
    return cx, cy


def _pointer_loc(desktop):
    import subprocess
    disp = getattr(desktop, "display", None) or os.environ.get("DISPLAY", ":0")
    out = subprocess.run(["xdotool", "getmouselocation"],
                         env={**os.environ, "DISPLAY": disp},
                         capture_output=True, text=True).stdout
    loc = dict(k.split(":") for k in out.split() if ":" in k)
    return int(loc.get("x", 0)), int(loc.get("y", 0))


def _viewport(desktop):
    # Only the X11 driver exposes root_size; force x11 (Xvfb target).
    d = Desktop(display=getattr(desktop, "display", None), backend="x11")
    try:
        return d.root_size()
    except Exception:
        return None


def record_interactive(desktop, display, shot_dir="/tmp"):
    rec = []
    field = {"n": 0}
    print("Recording macro. Position the mouse, press Enter to record a\n"
          "click; type 'q' then Enter to finish.\n")
    while True:
        x, y = _pointer_loc(desktop)
        reply = input(f"[{field['n']}] click @ {x},{y}? (Enter=record, "
                      f"t=<text to type> then record, q=quit): ").strip()
        if reply.lower() == "q":
            break
        p = perceive(screenshot(display=display, path=f"{shot_dir}/rec.png")[0],
                     with_ml=False)
        ln, fx, fy = _box_of_click(p, x, y)
        if ln is None:
            print("  ! no OCR line near that point — record a screen-mode "
                  "step instead? y/n", end=" ")
            if input().strip().lower() != "y":
                continue
            vp = _viewport(desktop) or {}
            W = vp.get("width") or (p.width or 1)
            H = vp.get("height") or (p.height or 1)
            rec.append(steps.click_step("", x / W, y / H, note="screen-mode",
                                        mode="screen"))
            field["n"] += 1
            continue
        value = None
        if reply.startswith("t="):
            value = reply[2:].strip()
        rec.append(steps.click_step(ln.text, fx, fy, note=ln.text) if value is
                   None else steps.type_step(ln.text, fx, fy, value,
                                             note=ln.text))
        field["n"] += 1
        print(f"  -> anchored to {ln.text!r} (fx={fx:.3f}, fy={fy:.3f})")
        time.sleep(0.2)
    return rec


def record_scripted(desktop, display, points, shot_dir="/tmp"):
    rec = []
    for i, (x, y, value) in enumerate(points):
        p = perceive(screenshot(display=display, path=f"{shot_dir}/rec.png")[0],
                     with_ml=False)
        ln, fx, fy = _box_of_click(p, x, y)
        if ln is None:
            print(f"[{i}] no line near ({x},{y}) — skipping")
            continue
        st = (steps.type_step(ln.text, fx, fy, value, note=ln.text) if value
              else steps.click_step(ln.text, fx, fy, note=ln.text))
        rec.append(st)
        print(f"[{i}] -> {ln.text!r} {value or 'click'}")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="output .macro.json path")
    ap.add_argument("--display", default=os.environ.get("DISPLAY", ":0"))
    ap.add_argument("--scripted", nargs="*",
                    help="x,y[,value] tuples instead of interactive")
    args = ap.parse_args()

    desktop = Desktop(display=args.display, backend="x11")
    vp = _viewport(desktop)
    if args.scripted:
        pts = []
        for tok in args.scripted:
            parts = tok.split(",")
            x, y = int(parts[0]), int(parts[1])
            pts.append((x, y, parts[2] if len(parts) > 2 else None))
        rec = record_scripted(desktop, args.display, pts)
    else:
        rec = record_interactive(desktop, args.display)
    steps.dump(rec, args.out, viewport=vp)
    print(f"\nwrote {args.out} ({len(rec)} steps), viewport {vp}")
    print(steps.pretty(rec))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Desktop OCR automation: capture screen -> tesseract OCR -> clicked coords (no CDP).
Subcommands:
  shot                 capture screen to /tmp/desk.png
  ocr [query]          dump all recognized words (optionally filtered, printed as `conf text`)
  find TEXT            print the pixel-center coords of the best word match, if any
  click TEXT           OCR-locate TEXT (fuzzy) and xdotool left-click its center
  clickat X Y          click absolute pixel coords
  type TEXT            xdotool type the given string
  scroll N             xdotool click wheel scroll (+up/-down), N lines
"""
import subprocess, sys, os, json, time, random, math

SHOT = os.environ.get("DESK_SHOT", "/tmp/desk.png")
OFFSET = {"x": 0, "y": 0}

def env():
    e = dict(os.environ)
    e.setdefault("DISPLAY", os.environ.get("DISPLAY", ":1"))
    e.setdefault("WAYLAND_DISPLAY", os.environ.get("WAYLAND_DISPLAY", "wayland-0"))
    e.setdefault("XAUTHORITY", "/run/user/1000/xauth_SATZtV")
    return e

def capture():
    wid = chromium_window_id()
    if wid:
        OFFSET["x"], OFFSET["y"] = wid[1], wid[2]
        r = subprocess.run(["import", "-window", str(wid[0]), SHOT], env=env(),
                           capture_output=True, text=True)
        if r.returncode == 0:
            return SHOT
    r = subprocess.run(["spectacle", "-f", "-b", "-n", "-o", SHOT], env=env(),
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("capture failed: " + r.stderr)
    return SHOT

def chromium_window_id():
    e = env()
    out = subprocess.run(["xdotool", "search", "--class", "chromium"], env=e,
                         capture_output=True, text=True).stdout.split()
    geom = None
    for wid in out:
        try:
            g = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid], env=e,
                               capture_output=True, text=True).stdout
        except Exception:
            continue
        vals = dict(l.split("=", 1) for l in g.split() if "=" in l)
        if vals.get("WIDTH") and int(vals.get("WIDTH", 0)) > 500 and \
           int(vals.get("HEIGHT", 0)) > 300:
            geom = (wid, int(vals.get("X", 0)), int(vals.get("Y", 0)))
            break
    return geom

def words():
    r = subprocess.run(["tesseract", SHOT, "stdout", "--psm", "11", "tsv"], env=env(),
                       capture_output=True, text=True)
    rows = []
    for line in r.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            left, top, width, height, conf = int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9]), float(parts[10])
        except ValueError:
            continue
        text = parts[11].strip()
        if text and conf > 30:
            rows.append({"text": text, "x": left + width // 2, "y": top + height // 2,
                         "left": left, "top": top, "w": width, "h": height, "conf": conf})
    return rows

def find(query):
    """Find a word sequence forming the phrase, clicking the best (highest conf) line."""
    q = query.lower().split()
    ws = words()
    best = None
    for i in range(len(ws)):
        if ws[i]["text"].lower() != q[0]:
            continue
        # walk subsequent words that are rightward on the same line
        seq = [ws[i]]
        prev = ws[i]
        for tok in q[1:]:
            nxt = None
            for w in ws:
                if (abs(w["y"] - prev["y"]) <= 8 and 0 < w["x"] - prev["x"] < 400 and
                        w["text"].lower() == tok):
                    nxt = w
                    break
            if nxt is None:
                break
            seq.append(nxt)
            prev = nxt
        if len(seq) == len(q):
            conf = sum(s["conf"] for s in seq) / len(seq)
            area = max(s["h"] for s in seq)
            score = (conf, area)
            if best is None or score > best[1]:
                cx = (seq[0]["x"] + seq[-1]["x"]) // 2
                cy = max(s["y"] for s in seq)
                best = ({"x": cx, "y": cy, "conf": conf}, score)
    return best[0] if best else None

def human_move(px, py):
    """Move the pointer to (px,py) along a smooth, human-looking curved path."""
    sx, sy = 0, 0
    try:
        cur = subprocess.run(["xdotool", "getmouselocation"], env=env(), capture_output=True,
                             text=True).stdout
        d = dict(k.split(':') for k in cur.split() if ':' in k)
        sx, sy = int(d.get('x', 0)), int(d.get('y', 0))
    except Exception:
        pass
    steps = random.randint(12, 22)
    # control point to add gentle curvature
    cx = (sx + px) / 2 + random.randint(-60, 60)
    cy = (sy + py) / 2 + random.randint(-40, 40)
    for i in range(1, steps + 1):
        t = i / steps
        # quadratic bezier
        x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t ** 2 * px
        y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t ** 2 * py
        x += random.uniform(-1.5, 1.5)
        y += random.uniform(-1.5, 1.5)
        subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))], env=env())
        time.sleep(random.uniform(0.008, 0.030))
    subprocess.run(["xdotool", "mousemove", str(px), str(py)], env=env())

def click(coord):
    px, py = coord[0] + OFFSET["x"], coord[1] + OFFSET["y"]
    if os.environ.get("INPUT_MODE", "ydotool") == "xdotool":
        human_move(px, py)
        time.sleep(random.uniform(0.05, 0.15))
        subprocess.run(["xdotool", "click", "1"], env=env())
    else:
        subprocess.run(["ydotool", "mousemove", "-a", "-x", str(px), "-y", str(py)], env=env())
        subprocess.run(["ydotool", "click", "0xC0"], env=env())  # left button down+up

def main():
    capture()
    args = sys.argv[1:]
    if not args:
        for w in words():
            print(f'{w["left"]:5} {w["top"]:5}  {w["text"]}')
        return
    cmd, rest = args[0], args[1:]
    if cmd == "ocrtxt":
        q = (rest[0] if rest else None)
        for w in words():
            if q is None or q.lower() in w["text"].lower():
                print(f'{w["x"]:5} {w["y"]:5}  {w["conf"]:6.1f}  {w["text"]}')
    elif cmd == "find":
        m = find(rest[0]) if rest else None
        print(json.dumps(m) if m else "NO_MATCH")
    elif cmd == "click":
        m = find(rest[0]) if rest else None
        if m:
            click((m["x"], m["y"]))
        print("NO_MATCH" if not m else f"clicked @ {m['x']},{m['y']}")
    elif cmd == "clickat":
        click((int(rest[0]), int(rest[1])))
        print("clicked")
    elif cmd == "type":
        subprocess.run(["ydotool", "type", " ".join(rest)], env=env())
        print("typed")
    elif cmd == "scroll":
        # wheel scroll: usage `scroll down 5` (or up)
        rep = int(rest[1]) if len(rest) > 1 else 3
        delta = -rep if rest[0].lower() == "down" else rep
        for _ in range(abs(rep)):
            subprocess.run(["ydotool", "mousemove", "-w", "-x", "0", "-y", str(delta)], env=env())
        print("scrolled")

if __name__ == "__main__":
    main()
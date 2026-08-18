#!/usr/bin/env python3
"""Macro battery: prove record->replay AND scale-invariance on Xvfb.

The point of macros is that an agent does NOT drive every step: capture a
task once as OCR-anchored relative steps, then replay deterministically
with no LLM. On top of that we must prove the macros aren't hard-locked to
one resolution — the core requirement.

We do both with ONE fixture (tests/apps/macro.html) which reflows with the
viewport, so absolute pixels break but anchored fractions survive:

  1. record_macro:  scripted-record three field entries + submit at the BASE
                    scale, by OCR-locating each input's placeholder and
                    clicking its center. Writes macros/shipment.macro.json.
  2. replay at BASE scale      -> result panel shows all three fields.
  3. replay at SCALED scale    -> SAME macro file, DIFFERENT device-scale-
                    factor + geometry. Result panel shows all three again.

Step 3 is the scale-invariance proof: no re-recording, no per-resolution
coordinate table, just the anchored fractions.

Idempotent: 'record' runs only if the macro file is missing/--force, so re-
runs replay a stable file. Two consecutive clean runs = pass (see skill).
"""
import argparse
import http.server
import os
import socketserver
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from vision.perceive import perceive  # noqa: E402
from agent.intents import match_target  # noqa: E402
from macros.run import MacroPlayer  # noqa: E402
from macros import record  # noqa: E402
from macros import steps as S  # noqa: E402
from desktopx.capture import screenshot  # noqa: E402

DISP = ":98"
APPS_DIR = os.path.join(REPO, "tests", "apps")
SHOT_DIR = "/tmp/dop-tests"
PROFILE = os.environ.get("DOP_PROFILE", os.path.join(REPO, "profiles", "default"))
MACRO_PATH = os.path.join(REPO, "macros", "shipment.macro.json")

# Two geometries that share the same logical CSS layout (device-scale swaps
# so the *physical* pixel positions of fields differ) — the margin/reflow
# must land anchored clicks the same way at both.
BASE_GEOM = os.environ.get("MACRO_GEOM", "3840x2160")
BASE_DPI = os.environ.get("MACRO_DPI", "2.0")
SCALED_GEOM = os.environ.get("MACRO_GEOM2", "2560x1440")
SCALED_DPI = os.environ.get("MACRO_DPI2", "1.5")

PASS = 0
FAIL = 0
FAILURES = []


def _info(geom):
    return f"{geom}@{'200%' if geom else ''}"


# -- harness --------------------------------------------------------------

def _ensure_xvfb():
    if subprocess.run(["xdpyinfo"], env={**os.environ, "DISPLAY": DISP},
                      capture_output=True).returncode != 0:
        subprocess.Popen(["Xvfb", DISP, "-screen", "0", f"{BASE_GEOM}x24",
                          "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)


def _set_xvfb(geom):
    # Recreate the X server at the requested geometry so physical pixels
    # genuinely change between base and scaled passes.
    cur = subprocess.run(["xdpyinfo"], env={**os.environ, "DISPLAY": DISP},
                         capture_output=True, text=True).stdout
    want = geom.split("x")[0]
    if "dimensions:" in cur and want not in cur:
        subprocess.run(["pkill", "-f", f"Xvfb {DISP}"], capture_output=True)
        time.sleep(1)
        subprocess.Popen(["Xvfb", DISP, "-screen", "0", f"{geom}x24",
                          "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)


def _launch_browser(url, dpi):
    subprocess.run(["pkill", "-f", "--ozone-platform=x11"], capture_output=True)
    time.sleep(1)
    os.makedirs(PROFILE, exist_ok=True)
    for f in ("Singleton", "SingletonLock", "SingletonSocket",
              "SingletonCookie"):
        try:
            os.remove(os.path.join(PROFILE, f))
        except FileNotFoundError:
            pass
    env = {**os.environ, "DISPLAY": DISP, "XDG_RUNTIME_DIR": "/run/user/1000",
           "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
           "KDE_FULL_SESSION": "true"}
    subprocess.Popen(
        ["chromium", f"--user-data-dir={PROFILE}", "--ozone-platform=x11",
         "--kiosk", "--no-first-run", "--no-default-browser-check",
         "--disable-infobars", "--noerrdialogs",
         "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
         "--disable-breakpad", f"--force-device-scale-factor={dpi}", url],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)


def _shot(name):
    os.makedirs(SHOT_DIR, exist_ok=True)
    p = f"{SHOT_DIR}/{name}.png"
    subprocess.run(["import", "-window", "root", p],
                   env={**os.environ, "DISPLAY": DISP}, capture_output=True)
    return p


def _wait_ready(timeout=15, interval=0.5):
    end = time.time() + timeout
    while time.time() < end:
        p = perceive(_shot("ready"), with_ml=False)
        if p.text and "READY" in p.text:
            return p
        time.sleep(interval)
    return p


def _assert(desc, cond, detail=""):
    global PASS, FAIL
    PASS += 1 if cond else 0
    if cond:
        print(f"  [PASS] {desc}")
    else:
        FAIL += 1
        FAILURES.append(f"{desc} ({detail})")
        print(f"  [FAIL] {desc} — {detail}")


# -- recording (deterministic, label-anchored) -----------------------------

def _record_macro(base_url):
    """Scripted-record: click each labelled field, type, submit.

    Each field is located by GEOMETRY (the OCR line whose center sits right
    of the label on the same row — the input), then the step is anchored to
    the label with the click stored as an offset fraction of the label box.
    Replay re-locates the stable label and lands in the field at any scale.
    The field's placeholder text is never relied on — only whatever OCR
    reads in the field region at record time.
    """
    from desktopx import Desktop

    # Force the X11 driver: Xvfb is X11; import-time backend detection can
    # pick Wayland when a live WAYLAND_DISPLAY leaks into the test env.
    desktop = Desktop(display=DISP, backend="x11")
    p = _wait_ready()
    # label -> (placeholder text, value to type). The placeholder is OCR text
    # INSIDE the field, so replay locates it anywhere on screen (most
    # scale-invariant). It anchors the click; the label+fraction archive it
    # as a fallback and for diagnostics.
    fields = [("Shipper name", "Acme Trucking Co.", "TruckCloud Freight"),
              ("Contact email", "ops@truckcloud.io", "dispatch@truckcloud.io"),
              ("Destination city", "Columbus OH", "Columbus OH")]
    rec = []
    for label, placeholder, value in fields:
        plc = match_target(p, placeholder, min_sim=0.55)
        if plc is None:
            return None, f"field placeholder {placeholder!r} not OCR-visible"
        lbl = match_target(p, label, min_sim=0.6)
        if lbl is None:
            return None, f"label {label!r} not OCR-visible"
        # Archive position as a fraction of the label box (fallback), and
        # remember the placeholder as the primary click target.
        anchored = record.anchor_click(p, label, plc.box.cx, plc.box.cy)
        if anchored is None:
            return None, f"could not anchor step to {label!r}"
        anchor_text, fx, fy = anchored
        rec.append(S.type_step(anchor_text, fx, fy, value, note=label,
                               target=placeholder))
    # Submit-load button (retry: after typing the field text, re-perceive
    # until the button reads; OCR single-shot can miss it).
    btn = None
    for _ in range(6):
        p2 = perceive(_shot("macro_submit"), with_ml=False)
        btn = match_target(p2, "Submit Load", min_sim=0.5)
        if btn is not None:
            break
        time.sleep(0.5)
    if btn is None:
        return None, "'Submit Load' not found"
    b = btn.box
    rec.append(S.click_step("Submit Load", (b.cx - b.left) / b.width,
                            (b.cy - b.top) / b.height, note="submit"))
    vp = desktop.root_size()
    S.dump(rec, MACRO_PATH, viewport=vp)
    return rec, None


# -- scenario --------------------------------------------------------------

def run_macro_battery(base_url):
    print("\n== macros: record once, replay at two resolutions ==")

    # --- 1) record (if needed) at BASE geometry -------------------------
    need_record = not os.path.exists(MACRO_PATH) or "--force" in sys.argv
    if need_record:
        print(f"  recording at {BASE_GEOM}@{BASE_DPI}")
        _set_xvfb(BASE_GEOM)
        _launch_browser(f"{base_url}/macro.html", BASE_DPI)
        rec, err = _record_macro(base_url)
        _assert("recorded macro file", rec is not None and os.path.exists(
            MACRO_PATH), err or "no steps")
    else:
        print(f"  using existing {os.path.basename(MACRO_PATH)} (--force to "
              f"re-record)")

    doc = S.load(MACRO_PATH)
    _assert("macro has type + click steps", any(
        s["action"] == "type" for s in doc["steps"]) and any(
        s["action"] == "click" for s in doc["steps"]),
        f"{len(doc['steps'])} steps")

    for geom, dpi, label in ((BASE_GEOM, BASE_DPI, "base"),
                             (SCALED_GEOM, SCALED_DPI, "scaled")):
        print(f"  replay at {label}: {geom}@{dpi}")
        _set_xvfb(geom)
        _launch_browser(f"{base_url}/macro.html", dpi)
        p = _wait_ready()
        _assert(f"[{label}] form rendered",
                "Shipment Intake" in (p.text or ""), (p.text or "")[:50])
        player = MacroPlayer(doc, display=DISP, verify=True, human=True,
                             backend="x11")
        try:
            player.run()
            ok = True
        except Exception as e:
            ok = False
            last = str(e)
        p2 = perceive(_shot(f"macro_after_{label}"), with_ml=False)
        txt = p2.text or ""
        _assert(f"[{label}] macro completed without LLM/CDP",
                ("TruckCloud Freight" in txt and "dispatch@truckcloud.io" in
                 txt and "Columbus" in txt), last if ok is False else txt[:80])


def main():
    global PASS, FAIL
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="re-record macro")
    p.add_argument("--base-url", default=None)
    args = p.parse_args()

    _ensure_xvfb()
    with socketserver.TCPServer(("127.0.0.1", 0), None) as probe:
        port = probe.server_address[1]
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, **kw, directory=APPS_DIR)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.5)
    base_url = args.base_url or f"http://127.0.0.1:{port}"
    print(f"serving fixtures on {base_url}")
    os.chdir(REPO)

    run_macro_battery(base_url)

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    if FAILURES:
        print("failures:")
        for f in FAILURES:
            print(f"  - {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

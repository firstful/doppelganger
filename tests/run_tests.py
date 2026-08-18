#!/usr/bin/env python3
"""End-to-end battery for the doppelganger stack on isolated Xvfb :98.

Each scenario: launch kiosk Chromium -> perceive() -> dispatch Intent(s)
-> re-perceive -> assert on OCR-visible state change. Screenshots only,
XTEST input only, no CDP/DOM. Asserts on what the screen actually shows.

Usage:
    ./tests/run_tests.py                  # full battery
    ./tests/run_tests.py --app counter    # one fixture
    ./tests/run_tests.py --with-llm       # use agent.do() (LLM intent) too
"""

import argparse
import http.server
import os
import re
import socketserver
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import vision  # noqa: E402
from vision.perceive import perceive  # noqa: E402
from agent.llm import Intent  # noqa: E402
from agent.intents import match_target, dispatch  # noqa: E402
from desktopx import Desktop  # noqa: E402

DISP = ":98"
GEOM = os.environ.get("DOP_GEOM", "3840x2160")  # 4K: real 2x glyphs for OCR
DPI_SCALE = os.environ.get("DOP_DPI", "2.0")     # 4K @ 200% = 1920x1080 logical
APPS_DIR = os.path.join(REPO, "tests", "apps")
SHOT_DIR = "/tmp/dop-tests"
# ONE persistent profile for everything (fixtures + real sites): sites see a
# browser with real cookies/history, not a fresh bot. Override via DOP_PROFILE.
PROFILE = os.environ.get(
    "DOP_PROFILE", os.path.join(REPO, "profiles", "default"))
BASE_URL = "http://127.0.0.1:0"  # set in main() after choosing a free port

PASS = 0
FAIL = 0
FAILURES = []


# -- harness --------------------------------------------------------------

def ensure_xvfb():
    if subprocess.run(["xdpyinfo"], env={**os.environ, "DISPLAY": DISP},
                      capture_output=True).returncode != 0:
        subprocess.Popen(["Xvfb", DISP, "-screen", "0", f"{GEOM}x24",
                          "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
    else:
        # Recreate at 4K if it's currently a lower-res server so price
        # glyphs get real 2x resolution. 4K@200% = 1920x1080 logical CSS px.
        info = subprocess.run(["xdpyinfo"],
                              env={**os.environ, "DISPLAY": DISP},
                              capture_output=True, text=True).stdout
        if "dimensions:" in info and GEOM.split("x")[0] not in info:
            subprocess.run(["pkill", "-f", "Xvfb", DISP], capture_output=True)
            time.sleep(1)
            subprocess.Popen(["Xvfb", DISP, "-screen", "0", f"{GEOM}x24",
                              "-nolisten", "tcp"],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            time.sleep(2)


def launch_browser(url):
    # Kill ALL kiosk Chromiums on this display; a stray browser from a prior
    # run steals clicks from the new one (both login to :98).
    subprocess.run(["pkill", "-f", "--ozone-platform=x11"],
                   capture_output=True)
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
        ["chromium", f"--user-data-dir={PROFILE}",
         "--ozone-platform=x11", "--kiosk", "--no-first-run",
         "--no-default-browser-check", "--disable-infobars",
         f"--force-device-scale-factor={DPI_SCALE}", url],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)  # let it paint + bind JS handlers


def shot(name):
    os.makedirs(SHOT_DIR, exist_ok=True)
    p = f"{SHOT_DIR}/{name}.png"
    subprocess.run(["import", "-window", "root", p],
                   env={**os.environ, "DISPLAY": DISP}, capture_output=True)
    return p


# -- assertions -----------------------------------------------------------

class Assertion:
    def __init__(self, desc, cond, detail=""):
        global PASS, FAIL
        self.desc, self.cond, self.detail = desc, bool(cond), detail
        if self.cond:
            PASS += 1
        else:
            FAIL += 1
            FAILURES.append(f"{desc} ({detail})")
        mark = "PASS" if self.cond else "FAIL"
        print(f"  [{mark}] {desc}" + (f" — {detail}" if detail else ""))


def wait_ready(timeout=15, interval=0.5):
    """Wait for the fixture's READY marker (JS handlers bound).

    The page paints HTML before scripts attach listeners; acting on a
    painted-but-not-interactive page is the #1 flake source. Each fixture
    appends a READY marker only after its handlers are bound.
    """
    end = time.time() + timeout
    while time.time() < end:
        p = perceive(shot("ready"), with_ml=False)
        if p.text and "READY" in p.text:
            return p
        time.sleep(interval)
    return p


# -- scenarios ------------------------------------------------------------

def run_counter(desktop):
    print("\n== counter: click increments visible count ==")
    launch_browser(f"{BASE_URL}/counter.html")

    p = wait_ready()
    Assertion("initial state shows Count: 0", "Count: 0" in (p.text or ""),
              (p.text or "")[:40])

    ln = match_target(p, "Add Unit")
    Assertion("found Add Unit button", ln is not None)
    if ln:
        dispatch(Intent(action="click", target="Add Unit"), p, desktop)
        time.sleep(0.8)
        p2 = perceive(shot("counter_after"), with_ml=False)
        Assertion("count incremented to 1",
                  "Count: 1" in (p2.text or ""), (p2.text or "")[:40])

        dispatch(Intent(action="click", target="Add Unit"), p2, desktop)
        time.sleep(0.8)
        p3 = perceive(shot("counter_2"), with_ml=False)
        Assertion("count incremented to 2",
                  "Count: 2" in (p3.text or ""), (p3.text or "")[:40])


def run_login(desktop):
    print("\n== login: type creds, submit, welcome shown ==")
    launch_browser(f"{BASE_URL}/login.html")

    p = wait_ready()
    Assertion("login form rendered", "Sign in to continue" in (p.text or ""),
              (p.text or "")[:60])

    # click the Email label (focuses the field via label[for])
    ln = match_target(p, "Email")
    Assertion("found Email label", ln is not None)
    if ln:
        dispatch(Intent(action="click", target="Email"), p, desktop)
        time.sleep(0.4)
        dispatch(Intent(action="type", target="Email", value="testuser"),
                 perceive(shot("login_user"), with_ml=False), desktop)

        p2 = perceive(shot("login_pass"), with_ml=False)
        ln2 = match_target(p2, "Password")
        Assertion("found Password label", ln2 is not None)
        if ln2:
            dispatch(Intent(action="click", target="Password"), p2, desktop)
            time.sleep(0.4)
            dispatch(Intent(action="type", target="Password",
                            value="hunter2"),
                     perceive(shot("login_pw_t"), with_ml=False), desktop)

        # submit
        p3 = perceive(shot("login_submit"), with_ml=False)
        if match_target(p3, "Sign In"):
            dispatch(Intent(action="click", target="Sign In"), p3, desktop)
            time.sleep(1.0)
            p4 = perceive(shot("login_welcome"), with_ml=False)
        else:
            p4 = p3
        Assertion("welcome message visible",
                  "Welcome, testuser!" in (p4.text or ""), (p4.text or "")[:60])


def run_dashboard(desktop):
    print("\n== dashboard: nav clicks swap page ==")
    launch_browser(f"{BASE_URL}/dashboard.html")

    p = wait_ready()
    Assertion("initial heading Overview",
              "Overview" in (p.text or ""), (p.text or "")[:60])
    Assertion("topbar badge visible", "LIVE" in (p.text or ""), (p.text or "")[:60])
    Assertion("table renders", "INV-2041" in (p.text or ""), (p.text or "")[:60])

    for page, expect in (("Transactions", "Transactions"),
                         ("Payouts", "Payouts"),
                         ("Settings", "Settings")):
        ln = match_target(p, page)
        Assertion(f"found {page} nav item", ln is not None)
        if ln:
            dispatch(Intent(action="click", target=page), p, desktop)
            time.sleep(0.8)
            p = perceive(shot(f"dash_{page.lower()}"), with_ml=False)
            shown = f"Showing the {page} page."
            Assertion(f"heading became {expect}",
                      expect in (p.text or "") and shown in (p.text or ""),
                      (p.text or "")[:70])
            # clicking the active nav item again is a no-op for the heading;
            # pick a different item next iteration
            time.sleep(0.3)


def run_scroll(desktop):
    print("\n== scroll: wheel reveals new items ==")
    launch_browser(f"{BASE_URL}/scroll.html")

    p = wait_ready()
    # First log item — OCR can misread "Boot sequence" (e.g. "200 sequence")
    # at high device scale, so assert on a substring that survives.
    Assertion("feed renders log items",
              "sequence" in (p.text or "") or "Boot" in (p.text or ""),
              (p.text or "")[:60])
    Assertion("colored severity badges read",
              "INFO" in (p.text or "") and "WARN" in (p.text or ""),
              ",".join(t for t in ("INFO", "WARN", "ERROR") if t in (p.text or "")))

    # Scroll down: 4K viewport shows more rows and needs more wheel ticks to
    # reach the tail than the old 1440x900 target. Scroll until the first
    # item leaves the viewport, up to a bound.
    from desktopx.input import scroll as wheel, move_to
    move_to(800, 500, display=DISP)
    for _ in range(60):  # generous bound for the tall 4K feed
        wheel(4, display=DISP)
        time.sleep(0.12)

    p = perceive(shot("scroll_bottom"), with_ml=False)
    seen = [t for t in ("Schema migrated", "Session pruned", "Mirror lag",
                        "Secret rotated", "Lease renewed")
            if t in (p.text or "")]
    Assertion("scrolled past top items",
              "Boot" not in (p.text or "") and "Queue drained" in (p.text or ""),
              (p.text or "")[:60])
    Assertion("reached bottom third of feed", bool(seen), ",".join(seen))


def run_prices(desktop):
    print("\n== prices: read superscript-cents product prices ==")
    launch_browser(f"{BASE_URL}/prices.html")

    p = wait_ready()
    Assertion("store renders",
              "Blue Ribbon" in (p.text or ""), (p.text or "")[:60])

    # Each card is $X.cc with superscript cents and a bulk tier below it.
    # Price recovery must produce clean "$12.98" style values, NOT the raw
    # "1298" run, and must NOT corrupt model numbers (660663, 300985, 15114).
    txt = p.text or ""
    for name, expect in (("Blue Ribbon", "$12.98"),
                         ("Plytanium", "$19.97"),
                         ("ProWood", "$13.24")):
        Assertion(f"{name} price recovered {expect}",
                  expect in txt, txt[:200])
    Assertion("bulk tier read", "$11.68" in txt, txt[:200])

    # Model numbers must never be tagged as prices (no invented currency).
    # If a model IS OCR'd (layout dependent), it must never carry a $ sign.
    for m in ("660663", "300985", "15114"):
        if m in txt:
            Assertion(f"model {m} not corrupted",
                      f"${m}" not in txt, txt[:250])
    # And exactly the expected currency tokens must exist (3 prices + tiers),
    # order-insensitive (OCR line order is scan order, not visual order).
    prices = sorted(re.findall(r"\$\d+\.\d{2}", txt))
    Assertion("only the 6 real prices/tiers recovered",
              prices == sorted(["$12.98", "$19.97", "$13.24",
                                "$11.68", "$17.82", "$11.95"]),
              str(prices))


def run_llm_smoke(desktop):
    """Optional: one full agent.do() loop through the real LLM gateway."""
    print("\n== llm smoke: agent.do('click Press Me') ==")
    launch_browser(f"{BASE_URL}/counter.html")
    p = wait_ready()
    Assertion("LLM smoke: initial Count: 0",
              "Count: 0" in (p.text or ""), (p.text or "")[:40])

    from agent import Agent
    a = Agent(display=DISP)
    report = a.do("click the Add Unit button", with_ml=False, verify=True)
    Assertion(f"agent.do ok: {report.summary}",
              report.ok, report.summary[:60])
    p2 = perceive(shot("llm_after"), with_ml=False)
    Assertion("LLM smoke: count incremented",
              "Count: 1" in (p2.text or "") or "Count: 2" in (p2.text or ""),
              (p2.text or "")[:40])


# -- main ---------------------------------------------------------------

def main():
    global PASS, FAIL, FAILURES
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=None, help="run one fixture only")
    ap.add_argument("--with-llm", action="store_true",
                    help="also run one full agent.do() LLM loop")
    args = ap.parse_args()

    print(f"repo: {REPO}\ndisplay: {DISP} ({GEOM})")
    ensure_xvfb()

    # serve fixtures on a free port
    with socketserver.TCPServer(("127.0.0.1", 0), None) as probe:
        port = probe.server_address[1]
    os.chdir(APPS_DIR)
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, **kw,
                                                                    directory=APPS_DIR)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.5)
    global BASE_URL
    BASE_URL = f"http://127.0.0.1:{port}"
    print(f"serving fixtures on {BASE_URL}")

    desktop = Desktop(display=DISP)

    os.chdir(REPO)
    scenes = {"counter": run_counter, "login": run_login,
              "dashboard": run_dashboard, "scroll": run_scroll,
              "prices": run_prices}
    if not args.app:
        print("\n=== full battery ===")
        for name, fn in scenes.items():
            try:
                fn(desktop)
            except Exception as e:
                global FAILURES
                FAILURES.append(f"{name}: exception {e}")
                FAIL += 1
        if args.with_llm:
            run_llm_smoke(desktop)
    else:
        scenes[args.app](desktop)
        if args.with_llm and args.app == "counter":
            run_llm_smoke(desktop)

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    if FAILURES:
        print("failures:")
        for f in FAILURES:
            print(f"  - {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
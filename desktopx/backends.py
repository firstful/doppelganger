"""Pluggable desktop drivers.

x11      -> xdotool / import (works on X servers, incl. Xvfb)
wayland  -> ydotool (kernel uinput; best effort window list = [])
windows  -> pyautogui + win32gui (optional, falls back to pyautogui)
macos    -> pyautogui (+ AppleScript window list, best effort)
"""
import os
import re
import subprocess
import time
import random
import shutil


def _run(args, env=None):
    return subprocess.run(args, env=env, capture_output=True, text=True)


class BaseDriver:
    name = "base"

    def list_windows(self):
        raise NotImplementedError

    def activate(self, win_id):
        raise NotImplementedError

    def raise_(self, win_id):
        raise NotImplementedError

    def geometry(self, win_id):
        raise NotImplementedError

    def move_resize(self, win_id, x=None, y=None, w=None, h=None):
        raise NotImplementedError

    def screenshot(self, win_id=None, path=None):
        raise NotImplementedError

    def click(self, x, y):
        raise NotImplementedError

    def move(self, x, y, human=True):
        raise NotImplementedError

    def type(self, text):
        raise NotImplementedError

    def scroll(self, amount):
        raise NotImplementedError


class X11Driver(BaseDriver):
    name = "x11"

    def __init__(self, display=None):
        self.display = display or os.environ.get("DISPLAY", ":0")
        if not shutil.which("xdotool"):
            raise RuntimeError("xdotool not installed")

    def _env(self):
        e = dict(os.environ)
        e["DISPLAY"] = self.display
        return e

    def list_windows(self):
        from .window import Window

        out = _run(["xdotool", "search", ""], env=self._env()).stdout.split()
        wins = []
        for wid in out:
            title = _run(["xdotool", "getwindowname", wid], env=self._env()).stdout.strip()
            cls = _run(["xdotool", "getwindowclassname", wid], env=self._env()).stdout.strip()
            if title or cls:
                wins.append(Window(self, int(wid), title, cls))
        return wins

    def _geometry(self, wid):
        out = _run(["xdotool", "getwindowgeometry", "--shell", str(wid)], env=self._env()).stdout
        d = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k] = int(v)
        return d

    def geometry(self, win_id):
        g = self._geometry(win_id)
        return {"x": g.get("X", 0), "y": g.get("Y", 0),
                "width": g.get("WIDTH", 0), "height": g.get("HEIGHT", 0)}

    def activate(self, win_id):
        _run(["xdotool", "windowactivate", "--sync", str(win_id)], env=self._env())

    def raise_(self, win_id):
        _run(["xdotool", "windowraise", str(win_id)], env=self._env())

    def move_resize(self, win_id, x=None, y=None, w=None, h=None):
        args = ["xdotool", "windowsize", str(win_id)]
        if w and h:
            args += [str(w), str(h)]
        _run(args, env=self._env())
        if x is not None and y is not None:
            _run(["xdotool", "windowmove", str(win_id), str(x), str(y)], env=self._env())

    def screenshot(self, win_id=None, path=None, screen=False):
        import re
        if screen or win_id is None:
            p = path or "/tmp/deskbx.png"
            _run(["import", "-window", "root", p], env=self._env())
            return p, self.root_size()
        g = self._geometry(win_id)
        p = path or "/tmp/deskbx.png"
        _run(["import", "-window", str(win_id), p], env=self._env())
        return p, {"width": g.get("WIDTH", 0), "height": g.get("HEIGHT", 0),
                   "x": g.get("X", 0), "y": g.get("Y", 0)}

    def root_size(self):
        out = _run(["xdpyinfo"], env=self._env()).stdout
        m = re.search(r"dimensions:\s+(\d+)x(\d+)", out)
        return {"width": int(m.group(1)), "height": int(m.group(2))} if m else None

    def _pointer(self):
        out = _run(["xdotool", "getmouselocation"], env=self._env()).stdout
        d = dict(k.split(":") for k in out.split() if ":" in k)
        return int(d.get("x", 0)), int(d.get("y", 0))

    def move(self, x, y, human=True):
        if not human:
            _run(["xdotool", "mousemove", str(int(x)), str(int(y))], env=self._env())
            return
        sx, sy = self._pointer()
        steps = random.randint(12, 18)
        cx = (sx + x) / 2 + random.randint(-60, 60)
        cy = (sy + y) / 2 + random.randint(-40, 40)
        for i in range(1, steps + 1):
            t = i / steps
            px = (1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t ** 2 * x
            py = (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t ** 2 * y
            px += random.uniform(-1.5, 1.5)
            py += random.uniform(-1.5, 1.5)
            _run(["xdotool", "mousemove", str(int(px)), str(int(py))], env=self._env())
            time.sleep(random.uniform(0.008, 0.03))
        _run(["xdotool", "mousemove", str(int(x)), str(int(y))], env=self._env())

    def click(self, x, y, human=True):
        self.move(x, y, human=human)
        time.sleep(random.uniform(0.05, 0.15))
        _run(["xdotool", "click", "1"], env=self._env())

    def type(self, text):
        _run(["xdotool", "type", "--delay", "40", text], env=self._env())

    def scroll(self, amount):
        _run(["xdotool", "click", "--repeat", str(abs(amount)),
              "5" if amount > 0 else "4"], env=self._env())


class WindowRef:
    def __init__(self, win_id, title, cls):
        self.id = win_id
        self.title = title
        self.cls = cls

    def __repr__(self):
        return f"<Window id={self.id} title={self.title!r} cls={self.cls!r}>"


class WaylandDriver(BaseDriver):
    name = "wayland"

    def __init__(self, socket=None):
        if not shutil.which("ydotool"):
            raise RuntimeError("ydotool not installed")
        self.socket = socket or os.path.expanduser(f"~/.ydotool_socket")

    def _env(self):
        e = dict(os.environ)
        e["YDOTOOL_SOCKET"] = self.socket
        return e

    def list_windows(self):
        # Wayland hides window enumeration from clients; rely on xdotool(XWayland).
        if os.system(f"xdpyinfo >/dev/null 2>&1") == 0:
            from .window import Window

            drv = X11Driver()
            return drv.list_windows()
        return []

    def activate(self, win_id):
        pass

    def raise_(self, win_id):
        pass

    def geometry(self, win_id):
        return {"x": 0, "y": 0, "width": 0, "height": 0}

    def move_resize(self, win_id, x=None, y=None, w=None, h=None):
        pass

    def screenshot(self, win_id=None, path=None):
        p = path or "/tmp/deskbx.png"
        _run(["spectacle", "-f", "-b", "-n", "-o", p], env=self._env())
        return p, None

    def move(self, x, y, human=True):
        _run(["ydotool", "mousemove", "-a", "-x", str(int(x)), "-y", str(int(y))], env=self._env())
        if human:
            time.sleep(random.uniform(0.05, 0.12))

    def click(self, x, y, human=True):
        self.move(x, y, human=False)
        time.sleep(0.05)
        _run(["ydotool", "click", "0xC0"], env=self._env())

    def type(self, text):
        _run(["ydotool", "type", text], env=self._env())

    def scroll(self, amount):
        y = -1 * amount if amount > 0 else amount
        _run(["ydotool", "mousemove", "-w", "-x", "0", "-y", str(y)], env=self._env())


def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = False
    return pyautogui


class WindowsDriver(BaseDriver):
    name = "windows"

    def list_windows(self):
        try:
            import win32gui

            wins = []
            tmp = []

            def cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    t = win32gui.GetWindowText(hwnd)
                    if t:
                        tmp.append(WindowRef(hwnd, t, win32gui.GetClassName(hwnd)))

            win32gui.EnumWindows(cb, None)
            return tmp
        except ImportError:
            return []

    def activate(self, win_id):
        try:
            import win32gui, win32con
            win32gui.SetForegroundWindow(win_id)
        except ImportError:
            pass

    def raise_(self, win_id):
        self.activate(win_id)

    def geometry(self, win_id):
        try:
            import win32gui
            return {"x": win32gui.GetWindowRect(win_id)[0],
                    "y": win32gui.GetWindowRect(win_id)[1],
                    "width": win32gui.GetWindowRect(win_id)[2] - win32gui.GetWindowRect(win_id)[0],
                    "height": win32gui.GetWindowRect(win_id)[3] - win32gui.GetWindowRect(win_id)[1]}
        except ImportError:
            return {"x": 0, "y": 0, "width": 0, "height": 0}

    def move_resize(self, win_id, x=None, y=None, w=None, h=None):
        try:
            import win32gui, win32con
            win32gui.SetWindowPos(win_id, None, x or 0, y or 0, w, h, win32con.SWP_NOZORDER)
        except ImportError:
            pass

    def screenshot(self, win_id=None, path=None):
        pg = _pyautogui()
        img = pg.screenshot()
        p = path or "/tmp/deskbx.png"
        img.save(p)
        return p, {"width": img.width, "height": img.height}

    def move(self, x, y, human=True):
        _pyautogui().moveTo(x, y, duration=random.uniform(0.4, 0.8))

    def click(self, x, y, human=True):
        self.move(x, y, human=human)
        _pyautogui().click()

    def type(self, text):
        _pyautogui().typewrite(text)

    def scroll(self, amount):
        _pyautogui().scroll(amount)


class MacDriver(WindowsDriver):
    name = "macos"

    def type(self, text):
        from pyautogui import write
        write(text)
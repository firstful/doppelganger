"""Platform / backend detection."""
import os
import platform
import shutil

BACKEND = None


def _x11_target(display):
    if not display:
        display = os.environ.get("DISPLAY", "")
    return display


def _xdpyinfo_ok(display):
    if not shutil.which("xdpyinfo"):
        return False
    d = _x11_target(display)
    return os.system(f"DISPLAY={d} xdpyinfo >/dev/null 2>&1") == 0


def detect_platform(display=None):
    sys = platform.system()

    if sys == "Windows":
        return "windows"
    if sys == "Darwin":
        return "macos"
    if sys == "Linux":
        return "linux"
    return "unknown"


def detect_backend(display=None):
    global BACKEND
    sys = platform.system()
    if sys == "Windows":
        BACKEND = "windows"
        return BACKEND
    if sys == "Darwin":
        BACKEND = "macos"
        return BACKEND

    # Linux: prefer a working X11 server else Wayland/other.
    if _xdpyinfo_ok(display):
        BACKEND = "x11"
    elif os.environ.get("WAYLAND_DISPLAY") or _xdpyinfo_ok(":98"):
        BACKEND = "wayland"
    else:
        BACKEND = "x11"
    return BACKEND


detect_backend()
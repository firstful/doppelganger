__all__ = ["Desktop", "discover_windows", "screenshot", "get_backend"]

import os

from .platform import detect_platform, BACKEND
from .window import Window, discover_windows
from .capture import screenshot
from .input import click_at, move_to, type_text, scroll, human_move
from .ocr import ocr_text, find_text, find_click


def Desktop(display=None, backend=None):
    """Return the active backend driver (WindowList source + input)."""
    b = backend or BACKEND
    if b == "x11":
        from .backends import X11Driver as backend_driver

        return backend_driver(display=display)
    if b == "wayland":
        from .backends import WaylandDriver as backend_driver

        return backend_driver(socket=None)
    if b == "windows":
        from .backends import WindowsDriver as backend_driver

        return backend_driver()
    if b == "macos":
        from .backends import MacDriver as backend_driver

        return backend_driver()
    raise RuntimeError(f"Unknown backend: {b}")


def get_backend():
    return BACKEND
"""Screen / window capture."""


def screenshot(window=None, path=None, display=None, screen=False):
    """Capture a specific window (or the whole display if window is None)."""
    from . import Desktop

    drv = Desktop(display=display)
    if window is not None and drv.name != "wayland":
        return drv.screenshot(window, path)
    return drv.screenshot(None, path, screen=screen)
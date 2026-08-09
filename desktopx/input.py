"""High-level desktop input helpers (cross-platform)."""


def _driver(display=None):
    from . import Desktop

    return Desktop(display=display)


def move_to(x, y, display=None, human=True):
    _driver(display).move(x, y, human=human)


def click_at(x, y, display=None, human=True):
    _driver(display).click(x, y, human=human)


def type_text(text, display=None):
    _driver(display).type(text)


def scroll(delta, display=None):
    _driver(display).scroll(delta)


def human_move(x, y, display=None):
    _driver(display).move(x, y, human=True)
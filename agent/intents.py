"""Intent dispatch: fuzzy target matching + concrete desktopx calls."""

import random
import time

from .llm import Intent


def fuzzy_sim(needle, haystack):
    """Token-overlap similarity in [0,1].

    Order-aware, substring-aware for reasonably long tokens only. A haystack
    with far fewer tokens than the needle scores low (no 1-token trap).
    """
    if not needle or not haystack:
        return 0.0
    n = [t for t in needle.lower().split() if t]
    h = [t for t in haystack.lower().split() if t]
    if not n or not h:
        return 0.0

    def tok_match(a, b):
        if a == b:
            return True
        longer, shorter = (a, b) if len(a) >= len(b) else (b, a)
        return len(shorter) >= 4 and shorter in longer

    hits = 0
    for tok in n:
        if any(tok_match(tok, x) for x in h):
            hits += 1
    # A needle longer than the line can't be fully present: cap by ratio.
    # A short needle inside a long line is fine (target 'login' in a heading).
    length_penalty = len(h) / len(n) if len(h) < len(n) else 1.0
    return (hits / len(n)) * length_penalty


def match_target(perception, text, min_sim=0.5):
    """Best fuzzy line match for `text` in a Perception, or None.

    Returns the matched line object (has .box with absolute px coords).
    """
    if not text:
        return None
    best, best_sim = None, 0.0
    for ln in perception.lines:
        sim = fuzzy_sim(text, ln.text)
        if sim > best_sim:
            best_sim = sim
            best = ln
    return best if best_sim >= min_sim else None


def _window_of(desktop, title_hint=None):
    """Pick the window to act on: a matching title, else the biggest one."""
    wins = desktop.list_windows()
    if not wins:
        return None
    if title_hint:
        for w in wins:
            if title_hint.lower() in (w.title or "").lower():
                return w
    return max(wins, key=lambda w: _area(w.geometry()))


def _area(g):
    return g.get("width", 0) * g.get("height", 0)


def dispatch(intent, perception, desktop, human=True, window=None):
    """Execute an Intent against a Perception. Returns an action-log dict."""
    action = intent.action
    log = {"action": action, "target": intent.target,
           "value": intent.value, "fallback": intent.fallback,
           "x": None, "y": None, "ok": False, "detail": ""}

    if action == "done":
        log["ok"] = True
        log["detail"] = "no-op"
        return log

    from desktopx.input import click_at, type_text, scroll as wheel

    if action in ("click", "type"):
        ln = match_target(perception, intent.target)
        if ln is None:
            log["detail"] = f"no match for {intent.target!r}"
            return log
        x, y = ln.box.cx, ln.box.cy
        log["x"], log["y"] = x, y
        click_at(x, y, display=getattr(desktop, "display", None), human=human)
        time.sleep(random.uniform(0.15, 0.35))
        if action == "type":
            if intent.value:
                type_text(intent.value,
                          display=getattr(desktop, "display", None))
                log["ok"] = True
                log["detail"] = f"typed {intent.value!r} into {intent.target!r}"
            else:
                log["detail"] = "type requested but no value provided"
        else:
            log["ok"] = True
            log["detail"] = f"clicked {intent.target!r}"
        return log

    if action == "scroll":
        delta = _scroll_delta(intent.value)
        wheel(delta, display=getattr(desktop, "display", None))
        log["ok"] = True
        log["detail"] = f"scrolled {intent.value or delta}"
        return log

    if action == "navigate":
        if intent.fallback:
            _press_key(desktop, "ctrl+l")
            time.sleep(0.15)
            type_text(intent.fallback, display=getattr(desktop, "display", None))
            time.sleep(0.1)
            _press_key(desktop, "Return")
            log["ok"] = True
            log["detail"] = f"navigated to {intent.fallback}"
        else:
            log["detail"] = "navigate requested but no URL (fallback) given"
        return log

    if action == "verify":
        ln = match_target(perception, intent.target)
        log["ok"] = ln is not None
        log["detail"] = (f"found {intent.target!r}" if ln
                         else f"NOT found: {intent.target!r}")
        return log

    log["detail"] = f"unknown action {action}"
    return log


def _scroll_delta(value):
    v = (value or "down").lower()
    return -4 if v.startswith("up") else 4


def _press_key(desktop, combo):
    from desktopx import Desktop

    d = Desktop(display=getattr(desktop, "display", None))
    d.press(combo)

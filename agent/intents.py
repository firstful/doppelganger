"""Intent dispatch: fuzzy target matching + concrete desktopx calls."""

import random
import time

from vision.models import Line
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
    """Best matching target rect for `text`, or None.

    Returns a pseudo-Line whose box is the TIGHTEST matching window of
    words: for a nav bar like "Home Settings Reports", asking for
    "Reports" returns a box around just "Reports", not the whole row —
    clicking the row center would hit the wrong link. Ties prefer smaller
    windows.
    """
    if not text:
        return None
    best, best_sim, best_n = None, 0.0, 10**9
    needle_n = len([t for t in text.lower().split() if t])
    for ln in perception.lines:
        words = sorted(ln.words, key=lambda w: w.box.left)
        n = len(words)
        for i in range(n):
            for j in range(i, n):
                window = words[i:j + 1]
                window_text = " ".join(w.text for w in window)
                sim = fuzzy_sim(text, window_text)
                # Dilute windows with extra unmatched words ("Sign In" must
                # not tie with "Sign in to continue": heading vs button).
                if needle_n:
                    dil = needle_n / (j - i + 1)
                    sim *= min(dil, 1.0)
                # Prefer a window that IS the whole line: a real button/link
                # is usually a row by itself, while natural-language headings
                # contain the target words inside longer text. Partial
                # windows inside a long line get a small penalty.
                if not (i == 0 and j == n - 1):
                    sim *= 0.9
                if sim > best_sim + 1e-9 or (
                        abs(sim - best_sim) <= 1e-9 and
                        len(window) < best_n):
                    pseudo = Line(window[0])
                    for extra in window[1:]:
                        pseudo.add(extra)
                    best_sim, best_n, best = sim, len(window), pseudo
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

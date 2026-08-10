"""Vision OCR: tesseract TSV -> word boxes and grouped text lines."""

import shutil
import subprocess

from .models import Word, Line


def _tsv(path, psm="11"):
    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract not installed")
    out = subprocess.run(
        ["tesseract", path, "stdout", "--psm", psm, "tsv"],
        capture_output=True, text=True).stdout
    return out


def ocr_words(path, psm="11"):
    """Return raw word boxes from tesseract TSV output."""
    words = []
    for line in _tsv(path, psm).splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            left, top = int(parts[6]), int(parts[7])
            width, height = int(parts[8]), int(parts[9])
            conf = float(parts[10])
        except ValueError:
            continue
        text = parts[11].strip()
        if text and conf > 30:
            words.append(Word(left, top, width, height, conf, text))
    return words


def group_lines(words, y_tol=8, gap_tol=160):
    """Group words into lines by row (same baseline) + horizontal proximity.

    Words on the same row whose gap is under `gap_tol` px belong to one line;
    large gaps (columns, spacing) start a new line.
    """
    lines = []
    for w in sorted(words, key=lambda w: (w.box.top, w.box.left)):
        placed = False
        for ln in lines:
            if abs(ln.box.top - w.box.top) <= y_tol:
                if w.box.left - ln.box.right <= gap_tol:
                    ln.add(w)
                    placed = True
                    break
        if not placed:
            lines.append(Line(w))
    return sorted(lines, key=lambda ln: (ln.box.top, ln.box.left))

def _x_overlap(a, b):
    return a.left < b.left + b.width and b.left < a.left + a.width

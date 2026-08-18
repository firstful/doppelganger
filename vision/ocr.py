"""Vision OCR: tesseract TSV -> word boxes and grouped text lines.

Small UI text (buttons, labels) is reliably read at 1.5x upscale; tesseract
at native resolution misses sub-40px glyphs. `OCR_SCALE` (default 1.5) is
applied before tesseract and all box coordinates are divided back down to
original image space, so callers never see scaled coordinates.

Two passes are merged: normal COLOR (tesseract's native binarization — dark
text, light text, and saturated text on light backgrounds like WARN/ERROR
badges all get real hue separation) and a saturation-mask inverse pass
(low-saturation pixels -> black, saturated background -> white) which makes
white text on ANY colored background — buttons, headers — readable as black
glyphs on white. Both are hue-independent. `OCR_DUAL` (default 1) controls
the second pass; 0 disables it for speed.
"""

import os
import shutil
import subprocess
import tempfile

from PIL import Image

from .models import Word, Line

OCR_SCALE = float(os.environ.get("OCR_SCALE", "1.5"))
OCR_DUAL = int(os.environ.get("OCR_DUAL", "1"))


def _prepare(path, mode="normal"):
    """Return (tempfile-of-prepared-image, scale).

    modes:
      normal  - grayscale (best general recall; dark-on-light and mid-tone
                text like green INFO badges on light green).
      color   - true color: tesseract's native binarization separates
                saturated text (orange WARN, red ERROR) from light
                backgrounds by hue, which grayscale flattens.
      inverse - saturation mask tuned to read text on colored backgrounds
                (buttons, badges, headers). Low-saturation pixels become
                black (text candidates), saturated pixels become white. The
                page's own background is usually gray/white (low saturation)
                and would flood the mask, so black regions connected to the
                image border are removed — that kills the page background
                while keeping enclosed text like "Sign In" on a colored
                button. Hue-independent: works for white text on any color.
    """
    scale = OCR_SCALE
    img = Image.open(path).convert("RGB")
    if mode == "inverse":
        a = img.resize((int(img.width * scale), int(img.height * scale)),
                       Image.LANCZOS)
        import numpy as np
        from scipy import ndimage

        arr = np.asarray(a).astype(np.float32)
        mx = arr.max(axis=2)
        mn = arr.min(axis=2)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
        mask = (sat < 0.25).astype(np.uint8)  # 1=text candidate (black)

        # Remove black components touching the image border (page bg flood).
        lab, n = ndimage.label(mask)
        border_labels = set(np.unique(np.concatenate([
            lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1] if lab.shape[1] > 1 else lab[:, 0]])))
        remove = np.zeros_like(mask)
        for lb in border_labels:
            if lb != 0:
                remove |= (lab == lb)
        # Keep non-border text candidates; everything else -> white.
        out = np.where((mask == 1) & (remove == 0), 0, 255).astype(np.uint8)
        tmp = tempfile.mktemp(suffix=".png")
        Image.fromarray(out).save(tmp)
        return tmp, scale
    if mode == "grayscale":
        img = img.convert("L")
    if scale > 1.0:
        w, h = img.size
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    fd, tmp = tempfile.mkstemp(suffix=".png")
    img.save(tmp)
    return tmp, scale


def _tsv(path, psm="11"):
    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract not installed")
    out = subprocess.run(
        ["tesseract", path, "stdout", "--psm", psm, "tsv"],
        capture_output=True, text=True).stdout
    return out


def _parse_tsv(tsv, scale):
    words = []
    for line in tsv.splitlines()[1:]:
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
            words.append(Word(round(left / scale), round(top / scale),
                              round(width / scale), round(height / scale),
                              conf, text))
    return words


def _overlap(a, b):
    """IoU-ish overlap of two word boxes; dedupe threshold."""
    ax1, ay1 = a.box.left, a.box.top
    ax2, ay2 = a.box.left + a.box.width, a.box.top + a.box.height
    bx1, by1 = b.box.left, b.box.top
    bx2, by2 = b.box.left + b.box.width, b.box.top + b.box.height
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    a_area = (ax2 - ax1) * (ay2 - ay1)
    b_area = (bx2 - bx1) * (by2 - by1)
    return inter / min(a_area, b_area) if min(a_area, b_area) else 0


def ocr_words(path, psm="11"):
    """Return raw word boxes from tesseract TSV output.

    Merges the normal and inverted passes, keeping the higher-confidence
    copy of any duplicate box. Coordinates are in ORIGINAL image space.
    """
    tmps = []
    try:
        passes = []
        for mode in (("grayscale", "color", "inverse") if OCR_DUAL
                     else ("grayscale",)):
            tmp, scale = _prepare(path, mode=mode)
            tmps.append(tmp)
            passes.append(_parse_tsv(_tsv(tmp, psm), scale))

        merged = []
        for words in passes:
            for w in words:
                dupe = False
                for m in merged:
                    if _overlap(w, m) > 0.5:
                        dupe = True
                        # Higher confidence wins wholesale (box included).
                        # A low-conf blob (e.g. tesseract misreading a colored
                        # button as one wide word) must never shadow a
                        # tight high-conf word from the other pass.
                        if w.conf > m.conf + 5:
                            m.box, m.conf, m.text = w.box, w.conf, w.text
                        break
                if not dupe:
                    merged.append(w)
        return merged
    finally:
        for tmp in tmps:
            try:
                os.unlink(tmp)
            except OSError:
                pass


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
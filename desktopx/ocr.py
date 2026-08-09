"""Tesseract OCR glue: read text, locate a phrase, optionally click it."""

import os
import shutil
import subprocess


def ocr_text(image_path, psm="11"):
    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract not installed")
    out = subprocess.run(["tesseract", image_path, "stdout", "--psm", psm],
                         capture_output=True, text=True).stdout
    return " ".join(out.split())


def _words(image_path, psm="11"):
    out = subprocess.run(["tesseract", image_path, "stdout", "--psm", psm, "tsv"],
                         capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            left, top, width, height = int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9])
            conf = float(parts[10])
        except ValueError:
            continue
        text = parts[11].strip()
        if text and conf > 30:
            rows.append({"text": text, "x": left + width // 2, "y": top + height // 2,
                         "conf": conf, "h": height})
    return rows


def find_text(query, image_path, psm="11"):
    """Find a phrase as a word sequence; return its center (x, y) or None."""
    q = query.lower().split()
    ws = _words(image_path, psm)
    best = None
    for i in range(len(ws)):
        if ws[i]["text"].lower() != q[0]:
            continue
        seq = [ws[i]]
        prev = ws[i]
        ok = True
        for tok in q[1:]:
            nxt = None
            for w in ws:
                if (abs(w["y"] - prev["y"]) <= 8 and 0 < w["x"] - prev["x"] < 400 and
                        w["text"].lower() == tok):
                    nxt = w
                    break
            if nxt is None:
                ok = False
                break
            seq.append(nxt)
            prev = nxt
        if ok and len(seq) == len(q):
            conf = sum(s["conf"] for s in seq) / len(seq)
            score = (conf, max(s["h"] for s in seq))
            if best is None or score > best[1]:
                best = ((seq[0]["x"] + seq[-1]["x"]) // 2,
                        max(s["y"] for s in seq), conf), score
    return best[0][:2] if best else None


def find_click(query, display=None, screenshot_path=None, offset=(0, 0)):
    """OCR-locate `query` on the current display and click its center.

    offset: (dx, dy) added to the OCR coordinate (e.g., window position).
    """
    from .capture import screenshot

    path, _ = screenshot(path=screenshot_path, display=display)
    loc = find_text(query, path)
    if loc is None:
        return None
    x, y = loc[0] + offset[0], loc[1] + offset[1]
    from .input import click_at

    click_at(x, y, display=display)
    return (x, y)
"""Price recovery: read currency amounts that general OCR mangles.

E-commerce prices are typographically hostile to tesseract: the dollar
figure is large, cents are small and raised (superscript), and there is
often no visible decimal point — "12" big + "98" small reads as the digit
run "1298". General OCR outputs "$12% 5561", drops the decimal, or merges
the $ into the first digit ("$12.98" -> "31298").

Two paths, both site-agnostic (keyed on the currency symbol, never vendor):

A. FAST PATH — the word already contains a currency symbol ($ £ €) and a
   plausible digit run (3-6 chars). Normalize that run directly ("$1048"
   -> $10.48). No re-crop needed; the main pass already read the digits.

B. CROP PATH — digit-only words (no symbol). These are ambiguous: "43110"
   is a zip, "660663" a model number, "31298" might be "$12.98" with the $
   misread as "3". Re-crop the ORIGINAL image tightly around the word,
   upscale 4x, re-read with a digit whitelist. Accept ONLY if the re-read
   contains a currency symbol — that proves it's a price, never a zip or
   model number. This is the safety rule that keeps recovery from
   inventing money.

Normalization: with >= 3 digits and no visible decimal, the last two
digits are cents ("1298" -> 12.98). Visible decimals are kept as-is.
"""

import os
import re
import shutil
import subprocess
import tempfile

from PIL import Image

_CURRENCY = re.compile(r"[$£€]")
_DIGITS = re.compile(r"\d[\d.,]*\d|\d")
_UPSCALE = float(os.environ.get("PRICE_UPSCALE", "4"))


def _tsv_text(path, psm="6"):
    if not shutil.which("tesseract"):
        return ""
    out = subprocess.run(
        ["tesseract", path, "stdout", "--psm", psm,
         "-c", "tessedit_char_whitelist=0123456789.$£€.,"],
        capture_output=True, text=True).stdout
    return out.strip()


def _normalize(raw):
    """Turn an OCR digit run into money, or None if implausible.

    Visible decimal -> keep (clamp 2 decimals). No decimal -> last two
    digits are cents, but only for runs of 3-6 chars (2-digit runs are
    quantities; 7+ runs are model numbers, not prices).
    """
    if not raw:
        return None
    groups = _DIGITS.findall(raw)
    for g in reversed(groups):
        s = g.replace(",", "").replace(".", "")
        if not s.isdigit():
            continue
        if not (3 <= len(s) <= 6):
            continue
        if "." in g:
            d, _, c = g.replace(",", "").partition(".")
            cents = (c + "00")[:2]
            return f"{int(d or 0)}.{cents}"
        if len(s) == 3:
            return f"{s[0]}.{s[1:]}"
        return f"{int(s[:-2])}.{s[-2:]}"
    return None


def _crop_read(img, box):
    """Tight high-scale re-read of one word region; returns raw text."""
    pad_x = max(12, box.width // 2)
    pad_top = max(14, box.height)
    pad_bot = max(8, box.height // 2)
    x0 = max(0, box.left - pad_x)
    y0 = max(0, box.top - pad_top)
    x1 = min(img.width, box.right + pad_x)
    y1 = min(img.height, box.bottom + pad_bot)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return ""
    crop = img.crop((x0, y0, x1, y1))
    scale = _UPSCALE
    big = crop.resize((int(crop.width * scale), int(crop.height * scale)),
                      Image.LANCZOS)
    fd, tmp = tempfile.mkstemp(suffix=".png")
    try:
        big.save(tmp)
        raw = _tsv_text(tmp, psm="6")
        if not raw:
            raw = _tsv_text(tmp, psm="7")
        return raw
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def recover_prices(image_path, words):
    """Return [(word, price_str)] for price candidates in `words`."""
    if not shutil.which("tesseract"):
        return []
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return []

    results = []
    for w in words:
        text = (w.text or "").strip()
        if not re.search(r"\d", text):
            continue
        has_currency = bool(_CURRENCY.search(text))

        # Fast path: symbol present, use the run the main pass already read.
        if has_currency:
            run = ""
            for g in reversed(_DIGITS.findall(text)):
                if g.replace(",", "").replace(".", "").isdigit():
                    run = g
                    break
            price = _normalize(run)
            if price:
                results.append((w, price))
                continue

        # Crop path: digit-only words (or failed fast path). Must prove it
        # is a price by re-reading a currency symbol from the actual pixels,
        # AND the run must be 3-4 chars (a real $X.XX / $XX.XX). Anything
        # longer is a model number/zip (300985 -> a hallucinated $ on a
        # model row), not a price.
        raw = _crop_read(img, w.box)
        if raw and _CURRENCY.search(raw):
            for g in reversed(_DIGITS.findall(raw)):
                s = g.replace(",", "").replace(".", "")
                if not s.isdigit():
                    continue
                # 3-4 char runs only: "998" ($9.98), "1298" ($12.98).
                # 5-6 char runs are model numbers / zips, never prices.
                if 3 <= len(s) <= 4:
                    price = _normalize(g)
                    if price:
                        results.append((w, price))
                    break
    return results


def tag_prices(image_path, words):
    """Replace price words with normalized money strings, in place.

    Only words recovered as prices are modified; everything else is left
    untouched (zips, model numbers, quantities, plain text).
    """
    replaced = []
    for w, price in recover_prices(image_path, words):
        w.text = f"${price}"
        replaced.append((w, price))
    return replaced
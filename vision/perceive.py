"""perceive: screenshot path -> structured Perception (OCR + optional ML)."""

from dataclasses import dataclass, field

from PIL import Image

from . import ml
from .ocr import ocr_words, group_lines


@dataclass
class Target:
    kind: str
    box: dict
    text: str
    conf: float
    source: str

    @property
    def cx(self):
        return self.box["left"] + self.box["w"] // 2

    @property
    def cy(self):
        return self.box["top"] + self.box["h"] // 2

    def as_dict(self):
        return {"kind": self.kind, "box": self.box, "text": self.text,
                "conf": self.conf, "source": self.source,
                "cx": self.cx, "cy": self.cy}


@dataclass
class Perception:
    path: str
    width: int
    height: int
    text: str
    words: list
    lines: list
    targets: list = field(default_factory=list)
    description: str = ""
    error: str = ""

    def as_dict(self):
        return {"path": self.path, "width": self.width, "height": self.height,
                "text": self.text, "error": self.error,
                "description": self.description,
                "lines": [{"box": ln.box.as_dict(), "text": ln.text,
                           "conf": ln.conf} for ln in self.lines],
                "words": [{"box": w.box.as_dict(), "conf": w.conf,
                           "text": w.text} for w in self.words],
                "targets": [t.as_dict() for t in self.targets]}

    def line_near(self, cx, cy, tol=20):
        """Return the text line closest to a point, or None."""
        best = None
        best_d = tol
        for ln in self.lines:
            d = max(abs(ln.box.cx - cx), abs(ln.box.cy - cy))
            if d < best_d:
                best_d = d
                best = ln
        return best

    def find_line(self, text):
        """Best fuzzy line match for a phrase, or None."""
        q = text.lower().split()
        best = None
        best_score = 0.0
        for ln in self.lines:
            words = [w.text.lower() for w in sorted(
                ln.words, key=lambda w: w.box.left)]
            hay = " ".join(words)
            if not hay:
                continue
            score = _token_sim(q, hay)
            if score > best_score:
                best_score = score
                best = ln
        return best if best_score >= 0.5 else None

    def target_for(self, text):
        """Best click target for a phrase, or None."""
        ln = self.find_line(text)
        if ln is None:
            return None
        for t in self.targets:
            if t.box["left"] == ln.box.left and t.box["top"] == ln.box.top:
                return t
        return Target("unknown", ln.box.as_dict(), ln.text, ln.conf, "ocr")


def _token_sim(needle, haystack):
    if not needle or not haystack:
        return 0.0
    h = haystack.split()
    if not h:
        return 0.0
    hits = 0
    for tok in needle:
        if any(tok in x or x in tok for x in h):
            hits += 1
    return hits / len(needle)


def load_image(path):
    return Image.open(path).convert("RGB")


def perceive(path, with_ml=True):
    """Run OCR + optional ML on a screenshot and return a Perception."""
    img = load_image(path)
    w, h = img.size
    words = ocr_words(path)
    lines = group_lines(words)
    text = " ".join(ln.text for ln in lines)
    p = Perception(path=path, width=w, height=h, text=text,
                   words=words, lines=lines)

    for ln in lines:
        p.targets.append(Target("ocr", ln.box.as_dict(), ln.text,
                                ln.conf, "ocr"))

    if with_ml:
        model = ml.get_model()
        if model is None:
            p.error = "ML unavailable (torch/transformers/weights missing)"
        else:
            try:
                p.description = model.describe(img)
                p.targets = _enrich_targets(p.targets, img)
            except Exception as e:  # never let ML break perception
                p.error = f"ML failed: {e}"
    return p


def _enrich_targets(targets, img):
    """Classify each target crop with ML (best effort, batched per image)."""
    model = ml.get_model()
    if model is None:
        return targets
    enriched = []
    for t in targets:
        box = t.box
        crop = img.crop((box["left"], box["top"],
                         box["left"] + box["w"], box["top"] + box["h"]))
        try:
            kind = model.kind(crop, t.text)
        except Exception:
            kind = "unknown"
        enriched.append(Target(kind, box, t.text, t.conf, "ml"))
    return enriched

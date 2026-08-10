"""Vision layer: OCR + local ML perception (Layer 2)."""

__all__ = ["perceive", "ocr_words", "group_lines", "get_model", "release",
           "Perception", "Target"]

from .perceive import perceive, Perception, Target
from .ocr import ocr_words, group_lines
from .ml import get_model, release

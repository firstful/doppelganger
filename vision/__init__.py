"""Vision layer: OCR + ML perception (Layer 2).

ML runs through the abstract `VisionBackend` interface (see `.backend`).
`ml.get_model()` picks a provider: local transformers Moondream2
(`Moondream2Model`), the vision.ffilt.us capability API (`VisionServiceModel`),
an OpenAI-compatible endpoint at `VISION_BASE` (`OpenAICompatModel`), or
Google Gemini (`GeminiModel`). Swap providers via `VISION_PROVIDER`, never
code.
"""

__all__ = ["perceive", "ocr_words", "group_lines", "get_model", "release",
           "Perception", "Target", "VisionBackend", "KINDS",
           "Moondream2Model", "VisionServiceModel", "OpenAICompatModel",
           "GeminiModel", "PROVIDERS"]

from .perceive import perceive, Perception, Target
from .ocr import ocr_words, group_lines
from .backend import VisionBackend, KINDS
from .providers import (Moondream2Model, VisionServiceModel, OpenAICompatModel,
                        GeminiModel, PROVIDERS)
from .ml import get_model, release

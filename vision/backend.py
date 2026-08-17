"""Abstract vision-model backend interface.

There is no single universal wire protocol for vision models (unlike
OpenAI-style chat completions for text LLMs), so we unify at the *capability*
level. Every provider — local transformers Moondream2, an OpenAI-compatible
llama-server/vLLM/Ollama endpoint, or Google Gemini's native REST API —
implements `VisionBackend` and adapts its own request/response format.

This keeps the agent (and `vision.perceive`) fully provider-agnostic: swap
providers by config, never by code.

Capabilities are declared per-backend via the `capabilities` frozenset
(one of "describe", "kind", "query", "detect") so callers can feature-check
before use. Best-effort by design: every method degrades to a safe default
("", "unknown", []) rather than raising.
"""

from abc import ABC, abstractmethod

KINDS = ("button", "link", "input", "image", "unknown")
CAPS = ("describe", "kind", "query", "detect")

_KIND_QUESTION = (
    "Answer with exactly one word. What kind of user-interface "
    "element is this? Choose from: button, link, input field, image, "
    "other."
)


def kind_question():
    """The canonical prompt used by every backend's `kind`."""
    return _KIND_QUESTION


def parse_kind(answer):
    """Map a free-form model answer onto the KINDS vocabulary."""
    a = (answer or "").lower()
    for k in ("button", "link"):
        if k in a:
            return k
    if "input" in a or "text" in a or "field" in a:
        return "input"
    if "image" in a:
        return "image"
    return "unknown"


class VisionBackend(ABC):
    """Interface every vision backend must implement."""

    name = "?"
    capabilities = frozenset()  # subset of CAPS

    @abstractmethod
    def describe(self, image):
        """Dense caption of the whole image -> str."""

    @abstractmethod
    def kind(self, image, text=""):
        """Classify one crop into KINDS -> str."""

    @abstractmethod
    def query(self, image, question):
        """Free-form visual question -> str."""

    @abstractmethod
    def detect(self, image, obj):
        """Bounding boxes for an object type -> list[dict]."""

    def has(self, cap):
        return cap in self.capabilities

    def release(self):
        """Free backend resources."""

"""Vision provider adapters. Each class is one wire format behind
`VisionBackend`; all are interchangeable through `ml.get_model()`.

  Moondream2Model    - local transformers (CPU fp32), native caption/query/detect
  VisionServiceModel - the vision.ffilt.us capability API (/v1/describe,
                       /v1/kind, /v1/query, /v1/detect) — primary remote path
  OpenAICompatModel  - OpenAI-compatible /v1/chat/completions with image_url
                       (direct llama-server/vLLM/Ollama, before the service)
  GeminiModel        - Google Gemini native REST (generateContent)

The public contract is the vision.ffilt.us capability API (SPEC-VISION-API);
OpenAI-compatible and Gemini REST are internal/interim wire formats.
"""

import base64
import io
import os

import requests
import urllib3

from .backend import CAPS, VisionBackend, kind_question, parse_kind

ENV_TIMEOUT = "30"


def _session():
    """Requests session for *.ffilt.us endpoints (self-signed TLS)."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    s = requests.Session()
    s.verify = False
    s.headers["User-Agent"] = "doppelganger/0.1"
    return s


def _image_data_url(image, fmt="JPEG", quality=85):
    """PIL Image -> `data:image/...;base64,...` (compact JPEG by default)."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format=fmt, quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64,{b64}"


def _image_b64(image, fmt="JPEG", quality=85):
    """PIL Image -> raw base64 string (for native REST APIs)."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format=fmt, quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _revision():
    return os.environ.get("VISION_MODEL_REVISION", "2025-06-21")


class Moondream2Model(VisionBackend):
    """Local Moondream2 via transformers (vikhyatk/moondream2, CPU fp32).

    Full capability set: describe, kind, query, detect.
    """

    name = "moondream2-local"
    capabilities = frozenset(CAPS)

    def __init__(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(
            "vikhyatk/moondream2", revision=_revision(),
            trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            "vikhyatk/moondream2", revision=_revision(),
            trust_remote_code=True)
        self.model.eval()

    def describe(self, image):
        try:
            return self.model.caption(image, length="normal")["caption"]
        except Exception:
            return ""

    def kind(self, image, text=""):
        return parse_kind(self.query(image, kind_question()))

    def query(self, image, question):
        try:
            return self.model.query(image, question)["answer"]
        except Exception:
            return ""

    def detect(self, image, obj):
        try:
            return self.model.detect(image, obj)["objects"]
        except Exception:
            return []

    def release(self):
        del self.model
        del self.tokenizer
        import gc

        gc.collect()


class VisionServiceModel(VisionBackend):
    """Consumer of the vision.ffilt.us capability API (SPEC-VISION-API).

    `detect` is supported only if the service's backend exposes it; the
    service returns [] otherwise.

    Env: VISION_BASE (default https://vision.ffilt.us), VISION_MODEL
    (default "florence-2"), VISION_API_KEY (optional Bearer),
    VISION_TIMEOUT (default 30s).
    """

    name = "vision.ffilt.us"
    capabilities = frozenset(("describe", "kind", "query"))

    def __init__(self, base=None, model=None, api_key=None, timeout=None):
        import requests

        self._requests = requests
        self.base = (base or os.environ.get(
            "VISION_BASE", "https://vision.ffilt.us")).rstrip("/")
        self.model = model or os.environ.get(
            "VISION_MODEL", "florence-2")
        self.timeout = float(timeout or os.environ.get("VISION_TIMEOUT",
                                                       ENV_TIMEOUT))
        self._session = _session()
        key = api_key or os.environ.get("VISION_API_KEY")
        if key:
            self._session.headers["Authorization"] = f"Bearer {key}"

    def ping(self):
        try:
            return bool(self._session.get(
                f"{self.base}/v1/models", timeout=2.0).ok)
        except Exception:
            return False

    def describe(self, image):
        try:
            return self._call("describe", image)["text"]
        except Exception:
            return ""

    def kind(self, image, text=""):
        try:
            return parse_kind(self._call("kind", image)["kind"])
        except Exception:
            return "unknown"

    def query(self, image, question):
        try:
            return self._call("query", image, question=question)["answer"]
        except Exception:
            return ""

    def detect(self, image, obj):
        try:
            return self._call("detect", image, object=obj)["objects"]
        except Exception:
            return []

    def release(self):
        if self._session is not None:
            self._session.close()
            self._session = None

    def _call(self, cap, image, question=None, object=None):
        url = f"{self.base}/v1/{cap}"
        payload = {"model": self.model, "image": _image_data_url(image)}
        if question is not None:
            payload["question"] = question
        if object is not None:
            payload["object"] = object
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()


class OpenAICompatModel(VisionBackend):
    """OpenAI-compatible /v1/chat/completions with image_url data URIs.

    Works against llama.cpp llama-server, vLLM, Ollama (OpenAI compat),
    LM Studio, and LiteLLM-style gateways that also proxy Gemini/Claude.
    No `detect` (the chat API has no bounding-box endpoint) -> degrades.

    Env: VISION_BASE (required), VISION_MODEL (default "moondream2"),
    VISION_API_KEY (optional Bearer), VISION_TIMEOUT (default 30s).
    """

    name = "openai-compat"
    capabilities = frozenset(("describe", "kind", "query"))

    def __init__(self, base=None, model=None, api_key=None, timeout=None):
        import requests

        self._requests = requests
        self.base = (base or os.environ.get("VISION_BASE", "")).rstrip("/")
        self.model = model or os.environ.get("VISION_MODEL", "moondream2")
        self.timeout = float(timeout or os.environ.get("VISION_TIMEOUT",
                                                       ENV_TIMEOUT))
        self._session = _session()
        key = api_key or os.environ.get("VISION_API_KEY")
        if key:
            self._session.headers["Authorization"] = f"Bearer {key}"
        if not self.base:
            raise ValueError("OpenAICompatModel needs VISION_BASE")

    def ping(self):
        """Quick reachability check (short timeout, never raises)."""
        try:
            return bool(self._session.get(
                f"{self.base}/v1/models", timeout=2.0).ok)
        except Exception:
            return False

    def describe(self, image):
        try:
            return self._chat(image, "Describe this screen.", max_tokens=128)
        except Exception:
            return ""

    def kind(self, image, text=""):
        try:
            return parse_kind(
                self._chat(image, kind_question(), max_tokens=16))
        except Exception:
            return "unknown"

    def query(self, image, question):
        try:
            return self._chat(image, question, max_tokens=128)
        except Exception:
            return ""

    def detect(self, image, obj):
        return []

    def release(self):
        if self._session is not None:
            self._session.close()
            self._session = None

    def _chat(self, image, text, max_tokens=64):
        url = f"{self.base}/v1/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url",
                     "image_url": {"url": _image_data_url(image)}},
                ],
            }],
        }
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


class GeminiModel(VisionBackend):
    """Google Gemini native REST (generateContent), no SDK dependency.

    `detect` is unsupported (no box endpoint) -> degrades to []. env:VISION_MODEL.

    Env: GEMINI_API_KEY (required), VISION_MODEL (default "gemini-2.5-flash"),
    VISION_TIMEOUT (default 30s).
    """

    name = "gemini"
    capabilities = frozenset(("describe", "kind", "query"))

    def __init__(self, model=None, api_key=None, timeout=None):
        import requests

        self._requests = requests
        self.model = model or os.environ.get("VISION_MODEL", "gemini-2.5-flash")
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.timeout = float(timeout or os.environ.get("VISION_TIMEOUT",
                                                       ENV_TIMEOUT))
        self._session = _session()
        if not self.api_key:
            raise ValueError("GeminiModel needs GEMINI_API_KEY")

    def ping(self):
        try:
            url = (f"https://generativelanguage.googleapis.com/v1beta/models"
                   f"?key={self.api_key}")
            return bool(self._session.get(url, timeout=2.0).ok)
        except Exception:
            return False

    def describe(self, image):
        try:
            return self._generate(image, "Describe this screen.",
                                  max_tokens=128)
        except Exception:
            return ""

    def kind(self, image, text=""):
        try:
            return parse_kind(
                self._generate(image, kind_question(), max_tokens=16))
        except Exception:
            return "unknown"

    def query(self, image, question):
        try:
            return self._generate(image, question, max_tokens=128)
        except Exception:
            return ""

    def detect(self, image, obj):
        return []

    def release(self):
        if self._session is not None:
            self._session.close()
            self._session = None

    def _generate(self, image, text, max_tokens=64):
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.api_key}")
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": text},
                    {"inline_data": {"mime_type": "image/jpeg",
                                     "data": _image_b64(image)}},
                ],
            }],
            "generationConfig": {"temperature": 0.1,
                                 "maxOutputTokens": max_tokens},
        }
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


PROVIDERS = {
    "moondream2": Moondream2Model,
    "vision": VisionServiceModel,
    "openai": OpenAICompatModel,
    "gemini": GeminiModel,
}


def _deps_available(cls):
    try:
        if cls is Moondream2Model:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        else:
            import requests  # noqa: F401
        return True
    except ImportError:
        return False

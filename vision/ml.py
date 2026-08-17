"""Vision model selection: pick a provider by config and cache it.

Best-effort by design: `get_model()` never raises. If no provider is usable
it returns None and the rest of vision runs on OCR alone.

Selection (env-driven):
  VISION_PROVIDER  auto | moondream2 | vision | openai | gemini
                   (default "auto")
  - "vision"    the vision.ffilt.us capability API; needs VISION_BASE set
                (defaults to https://vision.ffilt.us).
  - "openai"    direct OpenAI-compatible llama-server/vLLM/Ollama; needs
                VISION_BASE set to that endpoint.
  - "gemini"    needs GEMINI_API_KEY.
  - "moondream2" needs torch/transformers + weights (CPU fp32).
  - "auto"      vision (if VISION_BASE set) -> moondream2 (if torch) -> None.
  Any remote provider falls back to local moondream2 when unreachable.
"""

import os
import threading

from .providers import PROVIDERS, _deps_available, Moondream2Model

_global_lock = threading.Lock()
_global_model = None
_loading = False


def _provider_cls():
    provider = os.environ.get("VISION_PROVIDER", "auto").lower().strip()
    if provider == "auto":
        if os.environ.get("VISION_BASE", "").strip():
            return PROVIDERS["vision"]
        if _deps_available(Moondream2Model):
            return PROVIDERS["moondream2"]
        return None
    cls = PROVIDERS.get(provider)
    if cls is None or not _deps_available(cls):
        return None
    return cls


def get_model(force=False):
    """Return the process-wide VisionBackend singleton, or None.

    Never raises. For the "openai" provider, falls back to local moondream2
    when the remote endpoint is unreachable (ping fails).
    """
    global _global_model, _loading
    if _global_model is not None:
        return _global_model
    if _loading and not force:
        return None
    cls = _provider_cls()
    if cls is None:
        return None
    with _global_lock:
        if _global_model is not None:
            return _global_model
        _loading = True
        try:
            backend = cls()
            if hasattr(backend, "ping") and not backend.ping():
                backend.release()
                backend = None
                if _deps_available(Moondream2Model):
                    backend = Moondream2Model()
            _global_model = backend
        except Exception:
            _global_model = None
        finally:
            _loading = False
    return _global_model


def release():
    global _global_model
    if _global_model is not None:
        _global_model.release()
    _global_model = None

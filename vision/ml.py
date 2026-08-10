"""Local vision ML: Florence-2-base for click-target kinds + dense captions.

Best-effort by design: `get_model()` never raises. If torch/transformers or
the weights are unavailable it returns None and the rest of vision runs on
OCR alone.
"""

import os
import threading

KINDS = ("button", "link", "input", "image", "unknown")

_global_lock = threading.Lock()
_global_model = None
_loading = False


def _available():
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


class Model:
    """Lazy-loaded Florence-2-base wrapper (CPU)."""

    name = "florence-2-base"

    def __init__(self):
        import torch
        from transformers import AutoProcessor, AutoModelForCausalLM

        model_id = os.environ.get(
            "VISION_MODEL", "microsoft/Florence-2-base")
        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(
            model_id, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id, trust_remote_code=True)
        self.model.eval()

    def _infer(self, task, image, text=None):
        prompt = task
        if text is not None:
            prompt = f"<OCR>{text}</OCR>" if task.startswith("<") else f"{task} {text}"
        inputs = self.processor(text=prompt, images=image,
                                return_tensors="pt")
        with self.torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=512,
                                      num_beams=3)
        return self.processor.batch_decode(out, skip_special_tokens=False)[0]

    def describe(self, image):
        """Dense caption of the whole image."""
        return self._strip(self._infer("<DETAILED_CAPTION>", image))

    def kind(self, image, text=""):
        """Classify one crop into KINDS (best effort)."""
        try:
            label = self._infer("<CLASSIFY>", image, text or "button")
            low = label.lower()
            for k in KINDS:
                if k in low:
                    return k
            return "unknown"
        except Exception:
            return "unknown"

    def release(self):
        del self.model
        del self.processor
        self.torch.cuda.empty_cache() if self.torch.cuda.is_available() else None
        import gc

        gc.collect()

    @staticmethod
    def _strip(resp):
        if not resp:
            return ""
        resp = resp.replace("<DETAILED_CAPTION>", "").replace("</s>", "")
        return resp.strip()


def get_model(force=False):
    """Return the process-wide Model singleton, or None if unavailable."""
    global _global_model, _loading
    if _global_model is not None:
        return _global_model
    if _loading and not force:
        return None
    if not _available():
        return None
    with _global_lock:
        if _global_model is not None:
            return _global_model
        _loading = True
        try:
            _global_model = Model()
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

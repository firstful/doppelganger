"""Minimal OpenAI-compatible client for the llm.ffilt.us gateway.

No external SDKs. Self-signed TLS -> verify=False. No proxy.
"""

import json
import os
import urllib.request
import ssl

DEFAULT_BASE = "https://llm.ffilt.us"
DEFAULT_MODEL = "auto"


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, base=None, model=None, timeout=180):
        self.base = (base or os.environ.get("LLM_BASE") or DEFAULT_BASE).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def complete(self, system, user, json_mode=False):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            f"{self.base}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=self._ctx) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            raise LLMError(f"LLM request failed: {e}") from e
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Bad LLM response: {e}") from e
        if json_mode:
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError) as e:
                raise LLMError(f"LLM returned invalid JSON: {content[:200]}") from e
        return content

    def extract_intent(self, prompt):
        """Parse a prompt into {action, target, value, fallback}."""
        system = (
            "You turn a short UI-automation instruction into a single action. "
            "Reply only with JSON: {\"action\": ..., \"target\": ..., "
            "\"value\": ..., \"fallback\": ...}. "
            "action is one of: click, type, scroll, navigate, verify, done. "
            "target is the on-screen text to click or focus (empty if none). "
            "value is text to type, a scroll direction (up/down), or empty. "
            "fallback is a URL for navigate, a key-combo string to press "
            "first for type (e.g. 'Ctrl+L' to focus the address bar), or "
            "empty. If the instruction is not actionable on a desktop "
            "browser, use action=done."
        )
        try:
            obj = self.complete(system, prompt, json_mode=True)
            return Intent(
                action=str(obj.get("action", "done")).lower(),
                target=str(obj.get("target", "") or ""),
                value=str(obj.get("value", "") or ""),
                fallback=str(obj.get("fallback", "") or ""),
            )
        except Exception:
            return Intent(action="done")


class Intent:
    __slots__ = ("action", "target", "value", "fallback")

    def __init__(self, action="done", target="", value="", fallback=""):
        self.action = action
        self.target = target
        self.value = value
        self.fallback = fallback

    @property
    def valid(self):
        return self.action in {"click", "type", "scroll", "navigate",
                               "verify", "done"}

    def as_dict(self):
        return {"action": self.action, "target": self.target,
                "value": self.value, "fallback": self.fallback}

    def __repr__(self):
        return f"<Intent {self.as_dict()}>"

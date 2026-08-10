"""Agent loop: prompt -> intent -> perceive -> match -> act -> verify."""

import time
from dataclasses import dataclass, field

from .llm import LLM, Intent
from . import intents


@dataclass
class StepReport:
    prompt: str
    ok: bool
    summary: str
    actions: list = field(default_factory=list)
    perception: dict = field(default_factory=dict)
    intent: dict = field(default_factory=dict)
    before_text: str = ""
    after_text: str = ""

    def as_dict(self):
        return {"prompt": self.prompt, "ok": self.ok, "summary": self.summary,
                "actions": self.actions, "intent": self.intent}


class Agent:
    def __init__(self, llm=None, display=None, shot_dir="/tmp"):
        self.llm = llm or LLM()
        self.display = display
        self.shot_dir = shot_dir
        self._shot_n = 0

    # -- capture helpers -------------------------------------------------
    def capture(self, path=None):
        from desktopx.capture import screenshot

        if path is None:
            self._shot_n += 1
            path = f"{self.shot_dir}/agent_{self._shot_n}.png"
        p, _ = screenshot(display=self.display, path=path)
        return p

    def perceive(self, path=None, with_ml=True):
        from vision.perceive import perceive

        return perceive(self.capture(path), with_ml=with_ml)

    # -- main entry ------------------------------------------------------
    def do(self, prompt, timeout_s=120, with_ml=True, human=True,
           verify=True):
        """Run one prompt -> action -> verify cycle. Returns StepReport."""
        start = time.time()
        intent = self._safe_intent(prompt)
        report = StepReport(prompt=prompt, ok=False,
                            summary="failed to start")
        report.intent = intent.as_dict()

        try:
            p = self.perceive(with_ml=with_ml)
        except Exception as e:
            report.summary = f"perception failed: {e}"
            return report
        report.before_text = p.text
        report.perception = p.as_dict()

        from desktopx import Desktop

        desktop = Desktop(display=self.display)
        log = intents.dispatch(intent, p, desktop, human=human)

        if log["ok"] and verify:
            time.sleep(0.6)
            try:
                after = self.perceive(with_ml=False)
            except Exception:
                after = None
            report.after_text = after.text if after else ""
            changed = _changed(p.text, after.text if after else p.text)
            log["ok"] = changed or log["action"] in ("navigate", "done")

        report.actions.append(log)
        elapsed = time.time() - start
        report.ok = log["ok"]
        report.summary = (f"[{elapsed:.1f}s] {log['detail']}"
                          if log["ok"] else f"FAILED: {log['detail']}")
        return report

    def _safe_intent(self, prompt):
        try:
            i = self.llm.extract_intent(prompt)
            if not i.valid:
                return Intent(action="done")
            return i
        except Exception:
            return Intent(action="done")


def _changed(a, b):
    if not a or not b:
        return False
    a, b = set(a.lower().split()), set(b.lower().split())
    diff = a.symmetric_difference(b)
    return len(diff) >= 2

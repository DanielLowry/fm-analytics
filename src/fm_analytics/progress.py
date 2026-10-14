"""Best-effort, job-scoped progress from a capture subprocess."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time


class ProgressFile:
    """Publish one atomic JSON record, at most five times per second.

    Progress must never turn a successful read into a failed capture. Each
    invocation owns its sidecar; operational logs do not carry this protocol.
    """

    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()
        self._last = 0.0
        self._stage = ""

    def __call__(self, stage: str, completed: int = 0, total: int = 0, detail: str = "") -> None:
        if self.path is None:
            return
        with self._lock:
            now = time.monotonic()
            if stage == self._stage and completed != total and now - self._last < 0.2:
                return
            temporary = self.path.with_name(self.path.name + ".writing")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(json.dumps({
                    "stage": stage, "completed": completed, "total": total, "detail": detail,
                }), encoding="utf-8")
                os.replace(temporary, self.path)
                self._last, self._stage = now, stage
            except OSError:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

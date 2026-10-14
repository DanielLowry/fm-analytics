"""Watch the bounded scouting subprocess's atomic progress sidecar."""

from contextlib import contextmanager
import json
import threading


@contextmanager
def monitor_progress(path, callback):
    stopped = threading.Event()
    last = None

    def read():
        nonlocal last
        if callback is None:
            return
        try:
            raw = path.read_text(encoding="utf-8")
            if len(raw) > 4096 or raw == last:
                return
            event = json.loads(raw)
            stage, completed, total = event["stage"], event["completed"], event["total"]
            if (not isinstance(stage, str) or not isinstance(completed, int)
                    or not isinstance(total, int) or not 0 <= completed <= total):
                return
            callback(stage, completed, total, str(event.get("detail", ""))[:200])
            last = raw
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def watch():
        while not stopped.wait(0.2):
            read()

    worker = threading.Thread(target=watch, daemon=True, name="scouting-progress")
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join()
        read()

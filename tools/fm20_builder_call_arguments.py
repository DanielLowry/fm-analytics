#!/usr/bin/env python3
"""Research-only: capture FM's real arguments to the visible-result builder.

A systematic check against real FM attribute exports proved that the cold-
call harnesses' fabricated 5th argument (optional report object, hardcoded
null) and 6th argument (small caller context, hardcoded to {manager, 1})
sometimes produce a visible range where FM's own UI shows nothing -- for the
same attribute ID that is correct on other players. This tool never calls
into FM; it passively watches the same builder entry address the cold-call
tools target and records what FM's own code actually passes, for a genuine,
screen-triggered call, so the fabricated arguments can be compared against
reality.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_linux_probe import ProbeError
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_visibility_capture import (
    ERROR_PREFIX,
    CaptureError,
    _LineReader,
    _detach_gdb,
    _validated_module_base,
    _verify_inferior_alive,
    _wait_until_ready,
    VISIBLE_RESULT_BUILDER_RVA,
)

ARGS_PREFIX = "FMVIS_BUILDER_ARGS "
GDB_SCRIPT = Path(__file__).with_suffix(".gdb")


def capture_builder_arguments(
    pid: int,
    *,
    duration_seconds: float,
    proc_root: Path = Path("/proc"),
) -> list[dict[str, object]]:
    if duration_seconds <= 0:
        raise CaptureError("capture duration must be positive")
    if not GDB_SCRIPT.is_file():
        raise CaptureError(f"GDB capture script is missing: {GDB_SCRIPT}")

    module_base = _validated_module_base(pid, proc_root)
    environment = dict(os.environ)
    environment["FMVIS_MODULE_BASE"] = hex(module_base)
    environment["FMVIS_VISIBLE_RESULT_BUILDER_BREAKPOINT"] = hex(
        module_base + VISIBLE_RESULT_BUILDER_RVA
    )
    command = [
        "gdb", "-q", "-nx", "-ex", "set pagination off",
        "-ex", "set confirm off", "-ex", "set print thread-events off",
        "-ex", "handle SIGUSR1 nostop noprint pass",
        "-ex", f"source {GDB_SCRIPT}",
        "-p", str(pid),
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
        )
    except OSError as exc:
        raise CaptureError(f"cannot start GDB: {exc}") from exc

    reader = _LineReader(process)
    events: list[dict[str, object]] = []
    pending_error: CaptureError | None = None
    try:
        _wait_until_ready(process, reader)
        print(
            "Capture armed; redraw the target FM table/profile now.",
            file=sys.stderr,
            flush=True,
        )
        deadline = monotonic() + duration_seconds
        while monotonic() < deadline:
            line = reader.read_line(deadline - monotonic())
            if line is None:
                if process.poll() is not None:
                    raise CaptureError(
                        f"GDB exited unexpectedly with status {process.returncode}"
                    )
                continue
            if line.startswith(ERROR_PREFIX):
                raise CaptureError(line.removeprefix(ERROR_PREFIX))
            if line.startswith(ARGS_PREFIX):
                events.append(json.loads(line.removeprefix(ARGS_PREFIX)))
    except CaptureError as exc:
        pending_error = exc
    finally:
        detach_error = _detach_gdb(process, reader)
    if pending_error is not None:
        raise pending_error
    if detach_error is not None:
        raise detach_error
    _verify_inferior_alive(pid, proc_root)
    return events


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--duration", type=float, default=20.0)
    args = parser.parse_args(argv)
    try:
        events = capture_builder_arguments(
            choose_pid(args.pid), duration_seconds=args.duration
        )
    except (CaptureError, ProbeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "capturedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "count": len(events),
        "events": events,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

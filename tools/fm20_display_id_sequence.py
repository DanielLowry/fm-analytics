#!/usr/bin/env python3
"""Research-only: capture the *ordered* sequence of raw display-attribute IDs.

`fm20_visibility_capture.py --diagnostic-hits` proves the passive hook is
firing but only returns a deduplicated set, which loses the information this
tool needs: which raw ID fired for which on-screen column, in which order.

Only 8 of the ~40 entries in `DISPLAY_ATTRIBUTE_IDS` (the Physical block) were
ever verified against a real capture; every other entry is an unconfirmed
guess, and two guesses (Reflexes, Finishing) are now known wrong. This tool
does not guess a fix. It reuses the same passive, read-only hook already
proven safe for Physical, and prints the literal, ordered sequence of raw IDs
FM emits while a table redraws, so that sequence can be matched against the
on-screen column order the user reports for that exact view. It never reads
an attribute value and never calls into FM.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_linux_probe import ProbeError
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_visibility_capture import (
    ERROR_PREFIX,
    GDB_SCRIPT,
    CaptureError,
    _LineReader,
    _detach_gdb,
    _validated_module_base,
    _verify_inferior_alive,
    _wait_until_ready,
    build_gdb_environment,
    parse_diagnostic_hit,
)
from tools.fm20_visibility_trace import ATTRIBUTE_OFFSETS

import os
import subprocess
from datetime import UTC, datetime
from time import monotonic


def capture_ordered_ids(
    pid: int,
    *,
    duration_seconds: float,
    proc_root: Path = Path("/proc"),
) -> list[int]:
    """Return raw display-attribute IDs in the exact order the hook fired.

    Unlike `capture(..., diagnostic_hits=True)`, this keeps duplicates and
    order intact instead of collapsing them into a set, so a repeating
    per-row pattern can be read off directly.
    """

    if duration_seconds <= 0:
        raise CaptureError("capture duration must be positive")
    if not GDB_SCRIPT.is_file():
        raise CaptureError(f"GDB capture script is missing: {GDB_SCRIPT}")

    module_base = _validated_module_base(pid, proc_root)
    environment = build_gdb_environment(
        os.environ,
        module_base,
        tuple(sorted(ATTRIBUTE_OFFSETS)),
        (),
        diagnostic_hits=True,
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
    ordered_ids: list[int] = []
    pending_error: CaptureError | None = None
    try:
        _wait_until_ready(process, reader)
        print(
            "Capture armed; redraw the target FM table now.",
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
            attribute_id = parse_diagnostic_hit(line)
            if attribute_id is not None:
                ordered_ids.append(attribute_id)
    except CaptureError as exc:
        pending_error = exc
    finally:
        detach_error = _detach_gdb(process, reader)
    if pending_error is not None:
        raise pending_error
    if detach_error is not None:
        raise detach_error
    _verify_inferior_alive(pid, proc_root)
    return ordered_ids


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--duration", type=float, default=20.0)
    args = parser.parse_args(argv)
    try:
        ordered_ids = capture_ordered_ids(
            choose_pid(args.pid), duration_seconds=args.duration
        )
    except (CaptureError, ProbeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "capturedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "count": len(ordered_ids),
        "sequence": [f"0x{item:02x}" for item in ordered_ids],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

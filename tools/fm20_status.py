#!/usr/bin/env python3
"""The one answer to "is FM20 running, and what is its PID?".

Detection is by the executable's memory mapping (``find_fm20_processes``), never
by process name: under Proton the game shows up as ``S:\\common\\...\\fm.exe``, and
a ``pgrep fm.exe`` / ``ps | grep`` misses it. Exit codes let scripts and people
tell the three outcomes apart:

    0  running (PID printed)
    1  not running
    2  cannot tell (process view is restricted) -- never treat this as "not running"

Usage: python3 -m tools.fm20_status [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

from tools import fm20_linux_probe as probe


@dataclass(frozen=True)
class FmStatus:
    state: str  # "running" | "not_running" | "unknown"
    pids: tuple[int, ...] = ()
    detail: str = ""


def fm_status() -> FmStatus:
    """Never raises: an unreadable process view is ``unknown``, not ``not_running``."""
    try:
        pids = probe.find_fm20_processes()
    except probe.ProbeError as exc:
        return FmStatus("unknown", detail=str(exc))
    except OSError as exc:
        return FmStatus("unknown", detail=f"cannot read the process list: {exc}")
    if pids:
        return FmStatus("running", tuple(pids))
    return FmStatus("not_running")


def running_pid() -> int:
    """The PID to use, or a ProbeError that says why there isn't one."""
    status = fm_status()
    if status.state == "running":
        if len(status.pids) > 1:
            raise probe.ProbeError(f"more than one FM20 process found: {list(status.pids)}")
        return status.pids[0]
    raise probe.ProbeError(status.detail or "FM20 is not running")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status = fm_status()
    if args.json:
        print(json.dumps({"state": status.state, "pids": list(status.pids), "detail": status.detail}))
    elif status.state == "running":
        print(f"running pid={' '.join(map(str, status.pids))}")
    elif status.state == "not_running":
        print("not running")
    else:
        print(f"unknown: {status.detail}")
    return {"running": 0, "not_running": 1}.get(status.state, 2)


if __name__ == "__main__":
    sys.exit(main())

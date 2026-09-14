#!/usr/bin/env python3
"""Structured, on-by-default logging for every native call into FM.

Every ptrace attach, native function call, and identity-resolution memory
scan this project performs against the live FM process is logged here, on
by default, to a plain-text JSON-lines file. This is diagnostic only --
nothing about visibility or discoverability depends on this file -- and it
exists because FM crashed once during a large batch query with no other
usable evidence anywhere (dmesg showed nothing crash-specific, and our own
stdout had nothing either). The log's job is to answer, after the fact:
which exact call was in flight when something went wrong, and how many
calls had this process already made.

Enabled unconditionally; set FM20_LOG_PATH to redirect it, or FM20_LOG_DISABLE=1
to turn it off entirely (for a controlled experiment, not routine use).
Cross-process safe: appends are single, bounded writes with no Python-level
lock (O_APPEND is atomic for one write() below PIPE_BUF on Linux), since
multiple tool invocations and the monitor server can all be writing to this
file at the same time.
"""

from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "logs" / "fm20-native-calls.jsonl"
)
MAX_LOG_BYTES = 50 * 1024 * 1024  # rotate out old entries past ~50MB

_fd: int | None = None
_fd_path: Path | None = None
_call_sequence = itertools.count(1)
_disabled = os.environ.get("FM20_LOG_DISABLE") == "1"


def _log_path() -> Path:
    override = os.environ.get("FM20_LOG_PATH")
    return Path(override) if override else DEFAULT_LOG_PATH


def _rotate_if_large(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def _ensure_fd() -> int:
    global _fd, _fd_path
    path = _log_path()
    if _fd is not None and _fd_path == path:
        return _fd
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_large(path)
    _fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    _fd_path = path
    return _fd


def next_call_number() -> int:
    """A monotonic count of native calls made by this process, for spotting
    cumulative patterns (e.g. "failures cluster after ~N calls in one
    session") across incidents logged over time."""
    return next(_call_sequence)


def log_event(event: str, **fields: Any) -> None:
    """Append one structured event. Never raises: logging must not be able
    to break the native call it is describing, or the caller around it."""
    if _disabled:
        return
    try:
        record = {
            "ts": time.time(),
            "pid_self": os.getpid(),
            "event": event,
            **fields,
        }
        line = (json.dumps(record, default=str) + "\n").encode()
        os.write(_ensure_fd(), line)
    except OSError:
        pass

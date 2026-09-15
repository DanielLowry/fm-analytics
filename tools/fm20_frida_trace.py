#!/usr/bin/env python3
"""Bounded passive Frida hooks for the pinned FM20 process.

The adapter records call metadata and Win64 argument registers, never pointed-to
player data. It is research-only and is intended to be launched by
``tools/fm20_research.py``.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from tools.fm20_cold_visibility_call import EXPECTED_SHA256
from tools.fm20_linux_probe import ProbeError, parse_module_mapping, validate_executable


DEFAULT_REPORT_DIR = Path("data/research/frida")
SCHEMA_VERSION = 1
MAX_TARGETS = 8
MAX_EVENTS = 10_000


class FridaTraceError(RuntimeError):
    """A Frida trace failed its bounded safety or lifecycle checks."""


def preflight(pid: int, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    process = proc_root / str(pid)
    try:
        with (process / "maps").open(encoding="utf-8") as mappings:
            module_base, executable = parse_module_mapping(mappings)
    except OSError as error:
        raise FridaTraceError(f"cannot read process mappings: {error}") from error
    validate_executable(executable)
    with Path(executable).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != EXPECTED_SHA256:
        raise FridaTraceError("FM executable hash differs from the traced build")
    return {
        "pid": pid,
        "moduleBase": f"0x{module_base:x}",
        "executable": executable,
        "executableSha256": digest,
    }


def parse_target(value: str) -> dict[str, Any]:
    try:
        label, raw_rva = value.split("=", 1)
        rva = int(raw_rva, 0)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError("target must be LABEL=RVA") from error
    if not label or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in label):
        raise argparse.ArgumentTypeError("target label contains unsupported characters")
    if not 0 < rva < 0x80000000:
        raise argparse.ArgumentTypeError("target RVA is outside the bounded FM image range")
    return {"label": label, "rva": rva}


def build_agent_source(
    module_base: str,
    targets: Sequence[dict[str, Any]],
    max_events: int,
    capture_backtraces: bool,
) -> str:
    config = json.dumps({
        "moduleBase": module_base,
        "targets": [{"label": item["label"], "rva": item["rva"]} for item in targets],
        "maxEvents": max_events,
        "captureBacktraces": capture_backtraces,
    })
    return f"""
'use strict';
const config = {config};
const expectedBase = ptr(config.moduleBase);
const module = Process.enumerateModules().find(candidate => candidate.base.equals(expectedBase));
if (module === undefined) {{
  send({{kind: 'agent-error', error: 'FM module base was not found by Frida'}});
  throw new Error('FM module base was not found by Frida');
}}
let sequence = 0;
const listeners = [];
function relativeAddress(address) {{
  const owner = Process.findModuleByAddress(address);
  if (owner === null) return {{address: address.toString()}};
  return {{module: owner.name, rva: address.sub(owner.base).toString()}};
}}
for (const target of config.targets) {{
  const address = module.base.add(target.rva);
  if (address.compare(module.base.add(module.size)) >= 0) {{
    send({{kind: 'agent-error', error: 'target outside FM module', target: target.label}});
    throw new Error('target outside FM module');
  }}
  listeners.push(Interceptor.attach(address, {{
    onEnter(_args) {{
      if (sequence >= config.maxEvents) return;
      this.recorded = true;
      this.sequence = ++sequence;
      const event = {{
        kind: 'enter', sequence: this.sequence, target: target.label,
        targetRva: '0x' + target.rva.toString(16),
        threadId: Process.getCurrentThreadId(), timestampMs: Date.now(),
        returnAddress: relativeAddress(this.returnAddress),
        win64Arguments: {{
          rcx: this.context.rcx.toString(), rdx: this.context.rdx.toString(),
          r8: this.context.r8.toString(), r9: this.context.r9.toString()
        }}
      }};
      if (config.captureBacktraces) {{
        event.backtrace = Thread.backtrace(this.context, Backtracer.ACCURATE)
          .slice(0, 8).map(relativeAddress);
      }}
      send(event);
    }},
    onLeave(retval) {{
      if (!this.recorded) return;
      send({{
        kind: 'leave', sequence: this.sequence, target: target.label,
        threadId: Process.getCurrentThreadId(), timestampMs: Date.now(),
        returnValue: retval.toString()
      }});
    }}
  }}));
}}
send({{
  kind: 'ready', module: module.name, modulePath: module.path,
  moduleBase: module.base.toString(), moduleSize: module.size,
  targetCount: listeners.length
}});
"""


def capture(
    pid: int,
    module_base: str,
    targets: Sequence[dict[str, Any]],
    *,
    duration_seconds: float,
    max_events: int,
    capture_backtraces: bool,
    frida_api: Any,
    wait: Callable[[float], None] = time.sleep,
    ready_callback: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if not 0 <= len(targets) <= MAX_TARGETS:
        raise FridaTraceError(f"target count must be from 0 to {MAX_TARGETS}")
    if not 1 <= max_events <= MAX_EVENTS:
        raise FridaTraceError(f"max events must be from 1 to {MAX_EVENTS}")
    ready = threading.Event()
    messages: list[dict[str, Any]] = []
    agent_errors: list[dict[str, Any]] = []
    detached_events: list[dict[str, Any]] = []
    session = None
    script = None
    attached = False
    script_unloaded = False
    detached = False

    def on_message(message: dict[str, Any], _data: bytes | None) -> None:
        if message.get("type") == "send":
            payload = message.get("payload")
            if not isinstance(payload, dict):
                agent_errors.append({"kind": "invalid-payload"})
            elif payload.get("kind") == "ready":
                messages.append(payload)
                ready.set()
            elif payload.get("kind") == "agent-error":
                agent_errors.append(payload)
                ready.set()
            elif len(messages) <= max_events * 2 + 1:
                messages.append(payload)
        elif message.get("type") == "error":
            agent_errors.append({
                "kind": "script-error",
                "description": message.get("description"),
                "stack": message.get("stack"),
            })
            ready.set()

    def on_detached(reason: Any, crash: Any = None) -> None:
        detached_events.append({"reason": str(reason), "crash": str(crash) if crash else None})

    try:
        device = frida_api.get_local_device()
        session = device.attach(pid)
        attached = True
        session.on("detached", on_detached)
        source = build_agent_source(module_base, targets, max_events, capture_backtraces)
        script = session.create_script(source, name="fm20-bounded-trace")
        script.on("message", on_message)
        script.load()
        if not ready.wait(timeout=5):
            raise FridaTraceError("Frida agent did not report ready within five seconds")
        if agent_errors:
            raise FridaTraceError(agent_errors[0].get("error") or agent_errors[0].get("description") or "Frida agent failed")
        if ready_callback is not None:
            ready_callback()
        wait(duration_seconds)
    except Exception as error:  # Frida exposes binding-specific exception classes.
        agent_errors.append({
            "kind": "capture-error",
            "exceptionType": type(error).__name__,
            "description": str(error),
        })
    finally:
        if script is not None:
            try:
                script.unload()
                script_unloaded = True
            except Exception as error:  # Frida raises binding-specific subclasses.
                agent_errors.append({"kind": "script-unload-error", "description": str(error)})
        if session is not None:
            try:
                session.detach()
                detached = True
            except Exception as error:  # Frida raises binding-specific subclasses.
                agent_errors.append({"kind": "session-detach-error", "description": str(error)})

    ready_messages = [item for item in messages if item.get("kind") == "ready"]
    events = [item for item in messages if item.get("kind") in {"enter", "leave"}]
    return {
        "fridaVersion": str(frida_api.__version__),
        "attached": attached,
        "agentReady": len(ready_messages) == 1,
        "ready": ready_messages[0] if ready_messages else None,
        "events": events,
        "entryEventCount": sum(item.get("kind") == "enter" for item in events),
        "eventLimit": max_events,
        "eventLimitReached": sum(item.get("kind") == "enter" for item in events) >= max_events,
        "agentErrors": agent_errors,
        "scriptUnloaded": script_unloaded,
        "detached": detached,
        "detachEvents": detached_events,
    }


def process_alive(pid: int) -> bool:
    return (Path("/proc") / str(pid)).exists()


def summarize_events(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    targets: dict[str, dict[str, Any]] = {}
    for event in events:
        target = event.get("target")
        if not isinstance(target, str):
            continue
        summary = targets.setdefault(target, {
            "entryCount": 0,
            "leaveCount": 0,
            "threads": set(),
            "completedSequences": set(),
            "entrySequences": set(),
            "callers": Counter(),
            "returnValues": Counter(),
            "argumentValues": {register: set() for register in ("rcx", "rdx", "r8", "r9")},
        })
        thread_id = event.get("threadId")
        if thread_id is not None:
            summary["threads"].add(thread_id)
        sequence = event.get("sequence")
        if event.get("kind") == "enter":
            summary["entryCount"] += 1
            summary["entrySequences"].add(sequence)
            caller = json.dumps(event.get("returnAddress"), sort_keys=True)
            summary["callers"][caller] += 1
            for register, value in event.get("win64Arguments", {}).items():
                if register in summary["argumentValues"]:
                    summary["argumentValues"][register].add(value)
        elif event.get("kind") == "leave":
            summary["leaveCount"] += 1
            summary["completedSequences"].add(sequence)
            summary["returnValues"][str(event.get("returnValue"))] += 1

    serializable: dict[str, Any] = {}
    for target, summary in targets.items():
        completed = summary["entrySequences"] & summary["completedSequences"]
        serializable[target] = {
            "entryCount": summary["entryCount"],
            "leaveCount": summary["leaveCount"],
            "completedCallCount": len(completed),
            "threadIds": sorted(summary["threads"]),
            "distinctArgumentCounts": {
                register: len(values) for register, values in summary["argumentValues"].items()
            },
            "returnValueCounts": dict(summary["returnValues"].most_common(32)),
            "callerCounts": dict(summary["callers"].most_common(32)),
        }
    ranking = sorted(
        serializable,
        key=lambda target: (
            serializable[target]["entryCount"],
            len(serializable[target]["returnValueCounts"]),
            target,
        ),
        reverse=True,
    )
    return {"targets": serializable, "candidateRanking": ranking}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--module-base", required=True)
    parser.add_argument("--target", action="append", type=parse_target, default=[])
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--max-events", type=int, default=500)
    parser.add_argument("--backtraces", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "researchOnly": True,
        "adapter": "fm20-frida-trace",
        "createdAt": datetime.now(UTC).isoformat(),
        "status": "started",
        "targets": args.target,
        "durationSeconds": args.duration,
    }
    status = 1
    try:
        if not 0.25 <= args.duration <= 300:
            raise FridaTraceError("duration must be from 0.25 to 300 seconds")
        expected_base = int(args.module_base, 0)
        before = preflight(args.pid)
        if int(before["moduleBase"], 0) != expected_base:
            raise FridaTraceError("controller and adapter module bases differ")
        report["preflight"] = before
        try:
            frida_api = importlib.import_module("frida")
        except ImportError as error:
            raise FridaTraceError(
                "Frida is not installed; run with `uv run --extra research`"
            ) from error
        report["capture"] = capture(
            args.pid,
            before["moduleBase"],
            args.target,
            duration_seconds=args.duration,
            max_events=args.max_events,
            capture_backtraces=args.backtraces,
            frida_api=frida_api,
            ready_callback=lambda: print(
                f"ARMED: Frida attached for {args.duration:g} seconds; perform only the recipe's batched FM actions.",
                flush=True,
            ),
        )
        report["analysis"] = summarize_events(report["capture"]["events"])
        report["processAliveAfterDetach"] = process_alive(args.pid)
        capture_result = report["capture"]
        if not (
            capture_result["attached"]
            and capture_result["agentReady"]
            and capture_result["scriptUnloaded"]
            and capture_result["detached"]
            and not capture_result["agentErrors"]
            and report["processAliveAfterDetach"]
        ):
            detail = next(
                (
                    item.get("description")
                    for item in capture_result["agentErrors"]
                    if item.get("description")
                ),
                "unknown lifecycle failure",
            )
            raise FridaTraceError(f"Frida lifecycle did not complete cleanly: {detail}")
        report["status"] = "complete"
        status = 0
    except (FridaTraceError, ProbeError, OSError, ValueError) as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        report["processAliveAfterDetach"] = process_alive(args.pid)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        f"RESULT {args.report} status={report['status']} "
        f"events={report.get('capture', {}).get('entryEventCount', 0)}"
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())

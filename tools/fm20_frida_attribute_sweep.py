#!/usr/bin/env python3
"""Bulk manager-visible attribute reads through FM20's own visibility builder.

Research-only adapter launched by ``tools/fm20_research.py``. It calls FM's
already-proven, UI-verified visible-attribute builder (``guarded_native_call``
today does this one player/attribute at a time over ptrace) in-process, for
many players and every display attribute in one Frida session, on FM's own
UI thread. This is the scale answer to the footedness prototype: a per-call
ptrace attach/detach is workable for a single lookup and unworkable for a
squad-wide sweep.

The builder's ABI is unchanged from ``tools/fm20_cold_visibility_ptrace.py``:
``builder(context, result_out, player_interface, attribute_id, report=NULL,
caller_context=&{0, 1})``. Only the two visible bound bytes are ever read
back; the concealed third byte the render structure also carries is never
touched, matching ``fm_analytics.bridge.visibility_result``'s guarantee.

Scope is the managed first team, exactly like the footedness prototype: FM's
own visibility builder still needs the knowledge context and returns "visible
by this manager's knowledge" regardless of scope, but requesting a broader
population raises the unresolved discoverability question, not a Frida
limitation. See ``docs/research-automation.md`` for that gate.

Corrected 18 September 2026: the call used to fire on the next
``QueryPerformanceCounter`` tick on FM's UI thread, a moment FM did not choose
to be between units of work. It now prefers FM's message pump
(``GetMessageW``/``PeekMessageW``) instead -- see
``tools.fm20_frida_discoverability`` for the evidence that prompted this fix
in the Player Search pool rebuild agent, which this one shares the same risk
with (`tools.fm20_scouting_feed.hydrate_visible_attributes` is this module's
production caller).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from fm_analytics.bridge.visibility_result import decode_visible_bound_bytes
from tools.fm20_cold_query_cache import CONTEXT_ROOT_RVA
from tools.fm20_frida_trace import FridaTraceError, preflight, process_alive
from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    read_human_manager_contexts,
    read_i32,
    read_u64,
)
from tools.fm20_visibility_trace import DISPLAY_ATTRIBUTE_IDS


SCHEMA_VERSION = 1
MAX_PEOPLE = 64
BUILDER_RVA = 0x15A4A90
AGENT_TIMEOUT_SECONDS = 30.0

# See `tools.fm20_frida_discoverability.RESTING_POINT_EXPORTS` -- the same
# fix applies here: this agent's builder call is timed to whichever thread is
# the dominant `QueryPerformanceCounter` caller, but *when* on that thread it
# fires used to be "the next QPC call", not a point FM chose to be between
# units of work. Preferring the message pump moved the same risk in the
# Player Search pool rebuild; this hydration call carries the identical risk
# and had not been fixed.
RESTING_POINT_EXPORTS = ("GetMessageW", "GetMessageA", "PeekMessageW", "PeekMessageA")
THREAD_SAMPLE_EXPORT = "QueryPerformanceCounter"


class AttributeSweepError(RuntimeError):
    """A cold attribute sweep failed its bounded safety or evidence checks."""


def resolve_squad_and_context(memory_fd: int, module_base: int) -> tuple[int, list[dict[str, str]]]:
    """The manager's own knowledge context plus every managed player's interface.

    Mirrors ``tools/fm20_cold_query_cache.resolve_context_and_manager`` and the
    first-team walk in ``tools/fm20_linux_probe.read_first_team_squad``, but
    resolves the player-interface address the builder itself expects (the
    same address ``resolve_player_interfaces`` produces), not the person
    address the footedness adapter used.
    """
    root = read_u64(memory_fd, module_base + CONTEXT_ROOT_RVA)
    if not root:
        raise AttributeSweepError("manager-knowledge context root is missing")
    start = read_u64(memory_fd, root + 0x18)
    end = read_u64(memory_fd, root + 0x20)
    if not start or end - start != 8:
        raise AttributeSweepError("expected exactly one manager-knowledge context")
    context = read_u64(memory_fd, start)
    if not context:
        raise AttributeSweepError("manager-knowledge context is null")

    contexts = [item for item in read_human_manager_contexts(memory_fd, module_base) if item.manager.active]
    if len(contexts) != 1 or not contexts[0].team_address:
        raise AttributeSweepError("expected exactly one active manager with a first team")
    team = contexts[0].team_address
    squad_start = read_u64(memory_fd, team + 0x38)
    squad_end = read_u64(memory_fd, team + 0x40)
    if squad_start == 0 or squad_end < squad_start or (squad_end - squad_start) % 8 != 0:
        raise AttributeSweepError(f"invalid squad bounds 0x{squad_start:x}-0x{squad_end:x}")
    count = (squad_end - squad_start) // 8
    if count > MAX_PEOPLE:
        raise AttributeSweepError(f"implausible first-team squad size {count}")
    expected_vtable = module_base + FM20_4_4_STEAM.player_type_offset
    people: list[dict[str, str]] = []
    for index in range(count):
        try:
            slot = read_u64(memory_fd, squad_start + index * 8)
            # Same layout `resolve_player_interfaces` validates: a person
            # address is `player_interface + 0x1c8` (see
            # `tools/fm20_cold_query_cache._scan_player_interfaces`). The
            # squad slot holds the person address minus 0x8, one field short
            # of the interface -- do not reuse the unrelated `player_address
            # = slot + 0x8` convention `fm20_linux_probe.py` uses for the
            # squad reader's own, different offsets.
            person = slot + 0x1C8
            if read_u64(memory_fd, person) != expected_vtable:
                continue
            player_interface = person - 0x1C8
            actual = person + 0x28
            people.append({
                "id": str(read_i32(memory_fd, person + 0xC)),
                "interface": f"0x{player_interface:x}",
                "name_offset_a": f"0x{actual + 0x30:x}",
            })
        except (OSError, ProbeError):
            continue
    if not people:
        raise AttributeSweepError("managed first team contains no readable players")
    return context, people


AGENT_TEMPLATE = r"""
'use strict';
const config = __CONFIG__;
const fm = Process.getModuleByName('fm.exe');
if (!fm.base.equals(ptr(config.moduleBase))) {
  send({kind: 'error', error: 'FM module base differs from preflight'});
  throw new Error('FM module base differs from preflight');
}
const builderAddress = fm.base.add(config.builderRva);
// builder(context, result_out, player_interface, attribute_id, report, caller_context)
const builder = new NativeFunction(
  builderAddress, 'void', ['pointer', 'pointer', 'pointer', 'uint32', 'pointer', 'pointer']
);
const callerContext = Memory.alloc(16);
callerContext.writeU64(0);
callerContext.add(8).writeU64(1);
const result = Memory.alloc(16);

function callOne(playerAddress, attributeId) {
  result.writeU64(0xFFFFFFFFFFFFFFFF);
  builder(ptr(config.context), result, ptr(playerAddress), attributeId, ptr(0), callerContext);
  const bytes = result.readByteArray(2);
  const view = new Uint8Array(bytes);
  return {lower: view[0], upper: view[1]};
}

function runOnce() {
  const rows = [];
  for (const person of config.people) {
    const attributes = {};
    let errored = null;
    try {
      for (const [name, id] of Object.entries(config.attributes)) {
        attributes[name] = callOne(person.address, id);
      }
    } catch (error) {
      errored = String(error);
    }
    rows.push({id: person.id, attributes, error: errored});
  }
  send({kind: 'players', players: rows});
}

send({kind: 'ready', moduleBase: fm.base.toString(), people: config.people.length});
function findRestingPoint() {
  for (const name of config.restingPointExports) {
    const address = Module.findGlobalExportByName(name);
    if (address !== null) return {name, address};
  }
  return null;
}
const timing = Module.findGlobalExportByName(config.threadSampleExport);
if (timing === null) {
  send({kind: 'error', error: config.threadSampleExport + ' export not found'});
  throw new Error(config.threadSampleExport + ' export not found');
}
const sample = {};
const sampler = Interceptor.attach(timing, {onEnter() {
  const thread = Process.getCurrentThreadId();
  sample[thread] = (sample[thread] || 0) + 1;
}});
setTimeout(() => {
  sampler.detach();
  const ranked = Object.entries(sample).sort((a, b) => b[1] - a[1]);
  if (ranked.length === 0 || (ranked.length > 1 && ranked[0][1] < ranked[1][1] * 5)) {
    send({kind: 'error', error: 'no dominant FM UI thread was found'});
    return;
  }
  const thread = Number(ranked[0][0]);
  // Prefer the message loop, the same fix as the pool builder's agent; fall
  // back to the timing export only if FM exposes no message pump at all.
  const resting = findRestingPoint();
  const hook = resting === null ? {name: config.threadSampleExport, address: timing} : resting;
  send({kind: 'thread', thread, sample, hook: hook.name, restingPoint: resting !== null});
  let state = 'armed';
  const runner = Interceptor.attach(hook.address, {onEnter() {
    if (state !== 'armed' || Process.getCurrentThreadId() !== thread) return;
    state = 'running';
    try {
      runOnce();
    } catch (error) {
      send({kind: 'error', error: String(error)});
    }
    state = 'done';
    setTimeout(() => { runner.detach(); send({kind: 'finished'}); }, 0);
  }});
}, config.threadSampleMs);
"""


def build_agent_source(
    module_base: str, context: int, people: Sequence[dict[str, str]], attributes: Sequence[str]
) -> str:
    if not 1 <= len(people) <= MAX_PEOPLE:
        raise AttributeSweepError(f"person count must be from 1 to {MAX_PEOPLE}")
    unknown = set(attributes) - set(DISPLAY_ATTRIBUTE_IDS)
    if unknown:
        raise AttributeSweepError(f"unsupported attributes: {', '.join(sorted(unknown))}")
    if context <= 0:
        raise AttributeSweepError("knowledge context must be a positive address")
    for person in people:
        if int(person["interface"], 16) <= 0:
            raise AttributeSweepError("player interface address must be positive")
    config = {
        "moduleBase": module_base,
        "builderRva": BUILDER_RVA,
        "context": hex(context),
        "threadSampleMs": 1000,
        "people": [{"id": person["id"], "address": person["interface"]} for person in people],
        "attributes": {name: DISPLAY_ATTRIBUTE_IDS[name] for name in attributes},
        "restingPointExports": list(RESTING_POINT_EXPORTS),
        "threadSampleExport": THREAD_SAMPLE_EXPORT,
    }
    return AGENT_TEMPLATE.replace("__CONFIG__", json.dumps(config))


def extract(device: Any, target_pid: int, source: str, *, timeout_seconds: float = AGENT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Load the agent, wait for its single ``players`` batch, then detach."""
    finished = threading.Event()
    result: dict[str, Any] = {
        "attached": False,
        "agentReady": False,
        "thread": None,
        "players": [],
        "agentErrors": [],
        "scriptUnloaded": False,
        "detached": False,
        "detachEvents": [],
    }

    def on_message(message: dict[str, Any], _data: bytes | None) -> None:
        if message.get("type") != "send":
            result["agentErrors"].append({
                "kind": "script-error",
                "description": message.get("description"),
                "stack": message.get("stack"),
            })
            finished.set()
            return
        payload = message.get("payload")
        if not isinstance(payload, dict):
            result["agentErrors"].append({"kind": "invalid-payload"})
            return
        kind = payload.get("kind")
        if kind == "ready":
            result["agentReady"] = True
        elif kind == "thread":
            result["thread"] = {
                "id": payload.get("thread"),
                "qpcSample": payload.get("sample"),
                "hook": payload.get("hook"),
                "restingPoint": payload.get("restingPoint"),
            }
        elif kind == "players":
            result["players"] = payload.get("players", [])
        elif kind == "error":
            result["agentErrors"].append({"kind": "agent-error", "description": payload.get("error")})
            finished.set()
        elif kind == "finished":
            finished.set()

    def on_detached(reason: Any, crash: Any = None) -> None:
        result["detachEvents"].append({"reason": str(reason), "crash": str(crash) if crash else None})

    session = None
    script = None
    try:
        session = device.attach(target_pid)
        result["attached"] = True
        session.on("detached", on_detached)
        script = session.create_script(source, name="fm20-attribute-sweep")
        script.on("message", on_message)
        script.load()
        if not finished.wait(timeout_seconds):
            result["agentErrors"].append({
                "kind": "timeout",
                "description": f"agent did not finish within {timeout_seconds:g} seconds",
            })
    except Exception as error:  # Frida exposes binding-specific exception classes.
        result["agentErrors"].append({
            "kind": "capture-error",
            "exceptionType": type(error).__name__,
            "description": str(error),
        })
    finally:
        if script is not None:
            try:
                script.unload()
                result["scriptUnloaded"] = True
            except Exception as error:  # Frida raises binding-specific subclasses.
                result["agentErrors"].append({"kind": "script-unload-error", "description": str(error)})
        if session is not None:
            try:
                session.detach()
                result["detached"] = True
            except Exception as error:  # Frida raises binding-specific subclasses.
                result["agentErrors"].append({"kind": "session-detach-error", "description": str(error)})
    return result


def decode_capture(
    people: Sequence[dict[str, str]], attributes: Sequence[str], capture: dict[str, Any]
) -> dict[str, Any]:
    """Turn raw bound bytes into domain-shaped observations, never raw bytes."""
    rows_by_id = {row.get("id"): row for row in capture.get("players", []) if isinstance(row, dict)}
    players = []
    resolved = 0
    for person in people:
        row = rows_by_id.get(person["id"], {})
        if row.get("error"):
            players.append({"id": person["id"], "error": row["error"], "attributes": None})
            continue
        raw = row.get("attributes", {})
        if set(raw) != set(attributes):
            players.append({"id": person["id"], "error": "incomplete attribute set", "attributes": None})
            continue
        decoded: dict[str, Any] = {}
        try:
            for name in attributes:
                bounds = raw[name]
                observation = decode_visible_bound_bytes(bounds["lower"], bounds["upper"])
                decoded[name] = observation.to_dict()
        except (KeyError, TypeError, ValueError) as error:
            players.append({"id": person["id"], "error": str(error), "attributes": None})
            continue
        players.append({"id": person["id"], "error": None, "attributes": decoded})
        resolved += 1
    return {
        "scope": "managed-first-team",
        "source": "FM visible-attribute builder (RVA 0x15a4a90), swept in-process",
        "attributes": list(attributes),
        "requestedCount": len(people),
        "resolvedCount": resolved,
        "players": players,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--module-base", required=True)
    parser.add_argument("--remote-address", required=True, help="controller-owned Windows Frida server address")
    parser.add_argument("--remote-process", default="fm.exe")
    parser.add_argument("--attribute", action="append", choices=tuple(sorted(DISPLAY_ATTRIBUTE_IDS)))
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    attributes = tuple(args.attribute) if args.attribute else tuple(sorted(DISPLAY_ATTRIBUTE_IDS))
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "researchOnly": True,
        "adapter": "fm20-frida-attribute-sweep",
        "createdAt": datetime.now(UTC).isoformat(),
        "status": "started",
        "attributes": list(attributes),
        "safety": "guarded-native-call",
    }
    status = 1
    try:
        expected_base = int(args.module_base, 0)
        before = preflight(args.pid)
        if int(before["moduleBase"], 0) != expected_base:
            raise AttributeSweepError("controller and adapter module bases differ")
        report["preflight"] = before
        memory_fd = os.open(f"/proc/{args.pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
        try:
            context, people = resolve_squad_and_context(memory_fd, expected_base)
        finally:
            os.close(memory_fd)
        report["scope"] = {"kind": "managed-first-team", "playerCount": len(people)}
        try:
            frida_api = importlib.import_module("frida")
        except ImportError as error:
            raise AttributeSweepError("Frida is not installed; run with `uv run --extra research`") from error
        try:
            device = frida_api.get_device_manager().add_remote_device(args.remote_address)
            matches = [
                process
                for process in device.enumerate_processes()
                if process.name.casefold() == args.remote_process.casefold()
            ]
        except Exception as error:
            raise AttributeSweepError(
                f"cannot connect to Windows Frida server: {type(error).__name__}: {error}"
            ) from error
        if len(matches) != 1:
            raise AttributeSweepError(f"expected one remote {args.remote_process!r} process, found {len(matches)}")
        report["transport"] = {
            "kind": "windows-frida-server",
            "address": args.remote_address,
            "process": args.remote_process,
            "targetPid": matches[0].pid,
        }
        source = build_agent_source(before["moduleBase"], context, people, attributes)
        capture_result = extract(device, matches[0].pid, source)
        report["capture"] = {key: value for key, value in capture_result.items() if key != "players"}
        report["capture"]["fridaVersion"] = str(frida_api.__version__)
        report["extraction"] = decode_capture(people, attributes, capture_result)
        report["processAliveAfterDetach"] = process_alive(args.pid)
        if not (
            capture_result["attached"]
            and capture_result["agentReady"]
            and capture_result["scriptUnloaded"]
            and capture_result["detached"]
            and not capture_result["agentErrors"]
            and report["processAliveAfterDetach"]
        ):
            detail = next(
                (item.get("description") for item in capture_result["agentErrors"] if item.get("description")),
                "unknown lifecycle failure",
            )
            raise AttributeSweepError(f"Frida attribute sweep did not complete cleanly: {detail}")
        if report["extraction"]["resolvedCount"] != report["extraction"]["requestedCount"]:
            raise AttributeSweepError("not every managed player resolved a complete attribute set")
        report["status"] = "complete"
        status = 0
    except (AttributeSweepError, FridaTraceError, ProbeError, OSError, ValueError) as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        report["processAliveAfterDetach"] = process_alive(args.pid)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    extraction = report.get("extraction", {})
    print(
        f"RESULT {args.report} status={report['status']} "
        f"resolved={extraction.get('resolvedCount', 0)}/{extraction.get('requestedCount', 0)}"
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())

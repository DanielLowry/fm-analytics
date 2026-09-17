#!/usr/bin/env python3
"""Run FM20's manager-rooted Player Search path through Frida.

Research-only.  This is the Frida counterpart of
``fm20_discoverability_cold_query.py``: it resolves the native Player Search
source from the active manager with read-only memory checks, then calls the
known source builder and active full filter on FM's own UI thread.  It never
reads player attributes or publishes a bridge/API result.

The adapter is deliberately fail-closed.  A result is usable as research
evidence only when every source record was evaluated, the owned-player sample
has the expected exclusion behaviour, and manager/date/native arguments are
unchanged after the run.
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
from typing import Any, Callable, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from tools.fm20_discoverability_cold_filter import (
    FILTER_CONTEXT_VTABLE_RVA,
    FILTER_EVALUATOR_RVA,
    FILTER_VTABLE_RVA,
    MAX_COLD_RULE_CALLS,
    RECORD_WRAPPER_VTABLE_RVA,
    _source_records,
    resolve_full_filter,
    resolve_knowledge_context,
)
from tools.fm20_discoverability_cold_query import (
    own_contracted_ids,
    resolve_player_names,
    select_expected_exclusions,
    summarize,
)
from tools.fm20_discoverability_manager_builder import _live_context
from tools.fm20_frida_trace import FridaTraceError, preflight, process_alive
from tools.fm20_linux_probe import ProbeError, read_exact
from tools.fm20_linux_probe_runtime import choose_pid


SCHEMA_VERSION = 1
BUILDER_RVA = 0x52778C0
MAX_SOURCE_PLAYERS = MAX_COLD_RULE_CALLS
DEFAULT_CHUNK_SIZE = 25
MAX_CHUNK_SIZE = 100
AGENT_TIMEOUT_SECONDS = 300.0
OBSERVATION_REPORT_GLOB = "frida-player-search-filter-observation-*.adapter.json"
FILTER_THREAD_MODE_RVA = 0x7594438
FILTER_THREAD_A_RVA = 0x7594440
FILTER_THREAD_B_RVA = 0x7593598


class DiscoverabilityError(RuntimeError):
    """A Frida discoverability run failed an evidence or safety check."""


def _raise_with_report(report: dict[str, Any], message: str) -> None:
    error = DiscoverabilityError(message)
    error.report = report
    raise error


def _positive_address(value: int, label: str) -> None:
    if not isinstance(value, int) or value <= 0:
        raise DiscoverabilityError(f"{label} must be a positive address")


# Windows message-pump exports, in preference order. FM's UI thread returns to
# its message loop between units of work, so a hook here runs the builder at a
# resting point FM itself chose. `QueryPerformanceCounter` is a timing call FM
# makes *while* doing work -- it identifies the UI thread well but says nothing
# about what that thread is in the middle of, which is the assumption
# `docs/property-discovery-playbook.md` records as "at an idle point" and which
# does not follow. Kept last as a fallback, and always reported.
RESTING_POINT_EXPORTS = ("GetMessageW", "GetMessageA", "PeekMessageW", "PeekMessageA")
THREAD_SAMPLE_EXPORT = "QueryPerformanceCounter"


def builder_agent_source(module_base: str, arguments: tuple[int, int, int]) -> str:
    """Build one UI-thread invocation of the proven search-source builder.

    The invocation is timed to FM's message loop where one is reachable, so
    the builder runs between frames rather than wherever FM last happened to
    check a timer. The agent reports which hook it used in its ``thread``
    message, so a run that fell back to the timing hook is visible in the
    capture rather than silent.
    """
    source, manager_interface, team = arguments
    for value, label in ((source, "source"), (manager_interface, "manager interface"), (team, "team")):
        _positive_address(value, label)
    config = json.dumps({
        "moduleBase": module_base,
        "builderRva": BUILDER_RVA,
        "source": hex(source),
        "managerInterface": hex(manager_interface),
        "team": hex(team),
        "threadSampleMs": 1000,
        "restingPointExports": list(RESTING_POINT_EXPORTS),
        "threadSampleExport": THREAD_SAMPLE_EXPORT,
    })
    return f"""
'use strict';
const config = {config};
const fm = Process.getModuleByName('fm.exe');
if (!fm.base.equals(ptr(config.moduleBase))) throw new Error('FM module base differs from preflight');
const builder = new NativeFunction(fm.base.add(config.builderRva), 'uint64', ['pointer', 'pointer', 'pointer']);
function findRestingPoint() {{
  for (const name of config.restingPointExports) {{
    const address = Module.findGlobalExportByName(name);
    if (address !== null) return {{name, address}};
  }}
  return null;
}}
function selectUiThread(run) {{
  const timing = Module.findGlobalExportByName(config.threadSampleExport);
  if (timing === null) throw new Error(config.threadSampleExport + ' export not found');
  const sample = {{}};
  const sampler = Interceptor.attach(timing, {{onEnter() {{
    const id = Process.getCurrentThreadId(); sample[id] = (sample[id] || 0) + 1;
  }}}});
  setTimeout(() => {{
    sampler.detach();
    const ranked = Object.entries(sample).sort((a, b) => b[1] - a[1]);
    if (ranked.length === 0 || (ranked.length > 1 && ranked[0][1] < ranked[1][1] * 5)) {{
      send({{kind: 'error', error: 'no dominant FM UI thread was found'}}); return;
    }}
    const thread = Number(ranked[0][0]);
    // Prefer the message loop. Fall back to the timing export only if FM
    // exposes no message pump at all, and say which one was used either way.
    const resting = findRestingPoint();
    const hook = resting === null
      ? {{name: config.threadSampleExport, address: timing}} : resting;
    send({{kind: 'thread', thread, sample, hook: hook.name,
      restingPoint: resting !== null}});
    let state = 'armed';
    const runner = Interceptor.attach(hook.address, {{onEnter() {{
      if (state !== 'armed' || Process.getCurrentThreadId() !== thread) return;
      state = 'running';
      try {{ run(); }} catch (error) {{ send({{kind: 'error', error: String(error)}}); }}
      state = 'done';
      setTimeout(() => {{ runner.detach(); send({{kind: 'finished'}}); }}, 0);
    }}}});
  }}, config.threadSampleMs);
}}
send({{kind: 'ready', moduleBase: fm.base.toString()}});
selectUiThread(() => {{
  const result = builder(ptr(config.source), ptr(config.managerInterface), ptr(config.team));
  send({{kind: 'builder-result', returnValue: result.toString()}});
}});
"""


def filter_order(records: dict[int, int], own_ids: set[int]) -> tuple[list[dict[str, object]], int]:
    """Put a six-record behavioural guard ahead of the full native batch."""
    if not 1 <= len(records) <= MAX_SOURCE_PLAYERS:
        raise DiscoverabilityError(
            f"source player count must be from 1 to {MAX_SOURCE_PLAYERS}, got {len(records)}"
        )
    own = select_expected_exclusions(set(records), own_ids)
    excluded_sample = sorted(own)[:3]
    included_sample = sorted(set(records) - own_ids)[:3]
    if len(included_sample) != 3:
        raise DiscoverabilityError("fewer than three non-owned source players")
    ordered = excluded_sample + included_sample
    ordered.extend(player_id for player_id in sorted(records) if player_id not in set(ordered))
    rows = [
        {
            "id": str(player_id),
            "address": hex(records[player_id]),
            "expected": False if index < len(excluded_sample) else True,
        }
        for index, player_id in enumerate(ordered)
    ]
    return rows, len(excluded_sample) + len(included_sample)


def filter_agent_source(
    module_base: str,
    *,
    filter_object: int,
    manager_interface: int,
    team: int,
    knowledge_context: int,
    rows: Sequence[dict[str, object]],
    sample_count: int,
    chunk_size: int,
    thread_id: int,
    runtime_context: int | None = None,
    enforce_sample: bool = True,
) -> str:
    """Build a chunked FM-UI-thread batch of the proven full-filter callback."""
    for value, label in (
        (filter_object, "filter object"),
        (manager_interface, "manager interface"),
        (team, "team"),
        (knowledge_context, "knowledge context"),
    ):
        _positive_address(value, label)
    if not 1 <= len(rows) <= MAX_SOURCE_PLAYERS:
        raise DiscoverabilityError("filter row count is outside the bounded source limit")
    if not 1 <= sample_count <= len(rows):
        raise DiscoverabilityError("sample count is outside the filter row range")
    if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
        raise DiscoverabilityError(f"chunk size must be from 1 to {MAX_CHUNK_SIZE}")
    if not isinstance(thread_id, int) or thread_id <= 0:
        raise DiscoverabilityError("full-filter thread ID must be positive")
    if runtime_context is not None:
        _positive_address(runtime_context, "observed Player Search context")
    ids = [item.get("id") for item in rows]
    addresses = [item.get("address") for item in rows]
    if len(set(ids)) != len(ids) or any(not isinstance(item, str) or not item.isdigit() for item in ids):
        raise DiscoverabilityError("filter rows have invalid or duplicate player IDs")
    if any(not isinstance(item, str) or int(item, 16) <= 0 for item in addresses):
        raise DiscoverabilityError("filter rows have invalid player addresses")
    config = json.dumps({
        "moduleBase": module_base,
        "filterRva": FILTER_EVALUATOR_RVA,
        "filterContextVtableRva": FILTER_CONTEXT_VTABLE_RVA,
        "recordWrapperVtableRva": RECORD_WRAPPER_VTABLE_RVA,
        "filter": hex(filter_object),
        "managerInterface": hex(manager_interface),
        "team": hex(team),
        "knowledgeContext": hex(knowledge_context),
        "rows": list(rows),
        "sampleCount": sample_count,
        "chunkSize": chunk_size,
        "threadId": thread_id,
        "runtimeContext": hex(runtime_context) if runtime_context is not None else None,
        "enforceSample": enforce_sample,
        "threadSampleMs": 1000,
    })
    return f"""
'use strict';
const config = {config};
const fm = Process.getModuleByName('fm.exe');
if (!fm.base.equals(ptr(config.moduleBase))) throw new Error('FM module base differs from preflight');
const evaluator = new NativeFunction(fm.base.add(config.filterRva), 'uint8', ['pointer', 'pointer', 'pointer']);
const included = [];
let cursor = 0;
let sampleChecked = false;
const sampleMismatches = [];
let frameReported = false;
function fail(message) {{ send({{kind: 'error', error: message}}); }}
function makeCallFrame(stackPointer) {{
  // Keep the ptrace-proven object layout on FM's UI-thread stack.  The larger
  // reserve leaves room for Frida's NativeFunction call frame below the QPC
  // frame, so that wrapper cannot overwrite our context/record objects.
  const scratch = stackPointer.sub(0x4000);
  const filterContext = config.runtimeContext === null
    ? scratch.add(0x80) : ptr(config.runtimeContext);
  if (config.runtimeContext === null) {{
    filterContext.writePointer(fm.base.add(config.filterContextVtableRva));
    filterContext.add(8).writePointer(ptr(config.managerInterface));
    filterContext.add(0x10).writePointer(ptr(0));
    filterContext.add(0x18).writePointer(ptr(config.team));
    filterContext.add(0x20).writePointer(ptr(config.knowledgeContext));
  }}
  const record = scratch.add(0xc0);
  record.writePointer(fm.base.add(config.recordWrapperVtableRva));
  return {{filterContext, record}};
}}
function runChunk(stackPointer) {{
  const frame = makeCallFrame(stackPointer);
  const filterContext = frame.filterContext;
  const record = frame.record;
  const stop = Math.min(cursor + config.chunkSize, config.rows.length);
  for (; cursor < stop; cursor++) {{
    const row = config.rows[cursor];
    record.add(8).writePointer(ptr(row.address));
    if (!frameReported) {{
      frameReported = true;
      send({{kind: 'filter-frame', filter: ptr(config.filter).toString(), record: record.toString(),
        person: row.address, personVtable: ptr(row.address).readPointer().toString(),
        context: filterContext.toString(), contextVtable: config.runtimeContext === null ? filterContext.readPointer().toString() : null}});
    }}
    const visible = evaluator(ptr(config.filter), record, filterContext) !== 0;
    if (visible) included.push(row.id);
    if (cursor + 1 === config.sampleCount) {{
      for (let index = 0; index < config.sampleCount; index++) {{
        const expected = config.rows[index].expected;
        const actual = included.indexOf(config.rows[index].id) !== -1;
        if (actual !== expected) sampleMismatches.push(config.rows[index].id);
      }}
      if (config.enforceSample && sampleMismatches.length !== 0) {{
        throw new Error('native full-filter sample disagrees at player ' + sampleMismatches[0]);
      }}
      sampleChecked = true;
    }}
  }}
  send({{kind: 'progress', done: cursor, total: config.rows.length}});
  return cursor === config.rows.length;
}}
const qpc = Module.findGlobalExportByName('QueryPerformanceCounter');
if (qpc === null) throw new Error('QueryPerformanceCounter export not found');
const sample = {{}};
const sampler = Interceptor.attach(qpc, {{onEnter() {{
  const id = Process.getCurrentThreadId(); sample[id] = (sample[id] || 0) + 1;
}}}});
send({{kind: 'ready', moduleBase: fm.base.toString(), total: config.rows.length}});
setTimeout(() => {{
  sampler.detach();
  if (!(String(config.threadId) in sample)) {{
    fail('the required full-filter thread did not call QueryPerformanceCounter'); return;
  }}
  const thread = config.threadId;
  send({{kind: 'thread', thread, sample, selection: 'inactive-filter-thread'}});
  let state = 'armed';
  const runner = Interceptor.attach(qpc, {{onEnter() {{
    if (state !== 'armed' || Process.getCurrentThreadId() !== thread) return;
    state = 'running';
    try {{
      if (runChunk(this.context.rsp)) {{
        state = 'done';
        send({{kind: 'filter-result', includedPlayerIds: included, evaluatedCount: cursor, sampleChecked, sampleMismatches}});
        setTimeout(() => {{ runner.detach(); send({{kind: 'finished'}}); }}, 0);
        return;
      }}
      state = 'armed';
    }} catch (error) {{
      state = 'failed';
      send({{kind: 'error', error: String(error), errorType: typeof error,
        errorStack: error && error.stack ? String(error.stack) : null}});
      setTimeout(() => {{ runner.detach(); send({{kind: 'finished'}}); }}, 0);
    }}
  }}}});
}}, config.threadSampleMs);
"""


def extract(
    device: Any,
    target_pid: int,
    source: str,
    *,
    script_name: str,
    timeout_seconds: float = AGENT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run a single bounded Frida agent and preserve only approved results."""
    finished = threading.Event()
    result: dict[str, Any] = {
        "attached": False, "agentReady": False, "thread": None,
        "builderReturnValue": None, "includedPlayerIds": None,
        "evaluatedCount": None, "sampleChecked": False, "progress": [],
        "sampleMismatches": [],
        "filterFrame": None,
        "agentErrors": [], "scriptUnloaded": False, "detached": False,
        "detachEvents": [],
    }

    def on_message(message: dict[str, Any], _data: bytes | None) -> None:
        if message.get("type") != "send":
            result["agentErrors"].append({"kind": "script-error", "description": message.get("description")})
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
        elif kind == "builder-result":
            result["builderReturnValue"] = payload.get("returnValue")
        elif kind == "progress":
            result["progress"].append({"done": payload.get("done"), "total": payload.get("total")})
        elif kind == "filter-frame":
            result["filterFrame"] = {key: payload.get(key) for key in ("filter", "record", "person", "personVtable", "context", "contextVtable")}
        elif kind == "filter-result":
            result["includedPlayerIds"] = payload.get("includedPlayerIds")
            result["evaluatedCount"] = payload.get("evaluatedCount")
            result["sampleChecked"] = payload.get("sampleChecked") is True
            result["sampleMismatches"] = payload.get("sampleMismatches", [])
        elif kind == "error":
            result["agentErrors"].append({
                "kind": "agent-error", "description": payload.get("error"),
                "errorType": payload.get("errorType"), "stack": payload.get("errorStack"),
            })
            finished.set()
        elif kind == "finished":
            finished.set()

    def on_detached(reason: Any, crash: Any = None) -> None:
        result["detachEvents"].append({"reason": str(reason), "crash": str(crash) if crash else None})

    session = script = None
    try:
        session = device.attach(target_pid)
        result["attached"] = True
        session.on("detached", on_detached)
        script = session.create_script(source, name=script_name)
        script.on("message", on_message)
        script.load()
        if not finished.wait(timeout_seconds):
            result["agentErrors"].append({"kind": "timeout", "description": f"agent did not finish within {timeout_seconds:g} seconds"})
    except Exception as error:  # Frida exposes binding-specific exception classes.
        result["agentErrors"].append({"kind": "capture-error", "exceptionType": type(error).__name__, "description": str(error)})
    finally:
        if script is not None:
            try:
                script.unload()
                result["scriptUnloaded"] = True
            except Exception as error:
                result["agentErrors"].append({"kind": "script-unload-error", "description": str(error)})
        if session is not None:
            try:
                session.detach()
                result["detached"] = True
            except Exception as error:
                result["agentErrors"].append({"kind": "session-detach-error", "description": str(error)})
    return result


def decode_filter_capture(rows: Sequence[dict[str, object]], capture: dict[str, Any]) -> dict[int, bool]:
    """Validate a complete Frida result before turning it into a bool map."""
    if capture.get("evaluatedCount") != len(rows) or capture.get("sampleChecked") is not True:
        raise DiscoverabilityError("Frida did not complete and verify the full native filter batch")
    included = capture.get("includedPlayerIds")
    expected = {str(row["id"]) for row in rows}
    if not isinstance(included, list) or any(not isinstance(item, str) for item in included):
        raise DiscoverabilityError("Frida filter result has invalid included player IDs")
    actual = set(included)
    if len(actual) != len(included) or not actual <= expected:
        raise DiscoverabilityError("Frida filter result has duplicate or unknown player IDs")
    return {int(player_id): player_id in actual for player_id in expected}


def _active_manager(state: Any) -> Any:
    active = [manager for manager in state.human_managers if manager.active]
    if len(active) != 1 or active[0].club is None:
        raise DiscoverabilityError("expected one active human manager with a club")
    return active[0]


def _record_context(pid: int, module_base: int, source: int, manager_id: str) -> tuple[int, dict[int, int], int]:
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        reader: Callable[[int, int], bytes] = lambda address, size: read_exact(fd, address, size)
        return (
            resolve_full_filter(reader, module_base, source),
            _source_records(reader, source),
            resolve_knowledge_context(reader, module_base, manager_id),
        )
    finally:
        os.close(fd)


def latest_observed_context(pid: int, module_base: int, source: int) -> tuple[int, int, Path]:
    """Accept only a clean, same-session one-shot Player Search observation."""
    reports = sorted((Path("data/research/sessions")).glob(OBSERVATION_REPORT_GLOB), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        raise DiscoverabilityError("no Player Search one-shot observation report is available")
    for report_path in reports:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            preflight = report["preflight"]
            capture = report["capture"]
            events = capture["events"]
            event = events[0]
            if not (
                report.get("status") == "complete"
                and preflight.get("pid") == pid
                and int(preflight.get("moduleBase"), 0) == module_base
                and capture.get("attached") and capture.get("agentReady")
                and capture.get("scriptUnloaded") and capture.get("detached")
                and not capture.get("agentErrors")
                and len(events) == 1
                and event.get("kind") == "enter"
                and event.get("target") == "player-search-filter-pass"
                and int(event["win64Arguments"]["rcx"], 0) == source
            ):
                continue
            context = int(event["win64StackArgument5"], 0)
            thread = int(event["threadId"])
            _positive_address(context, "observed Player Search context")
            if thread <= 0:
                continue
            return context, thread, report_path
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            continue
    raise DiscoverabilityError("no clean Player Search observation matches the current FM session and source")


def resolve_filter_thread(pid: int, module_base: int) -> tuple[int, dict[str, int]]:
    """Choose the non-current thread for the filter wrapper's special branch.

    The wrapper at 0x5337010 maps records through a thread-local registry only
    when the current Windows thread equals its active-thread global.  That
    path is for FM's render loop and faults without its UI-only cache.  The
    established cold call instead needs the alternate live FM thread, which
    takes the normal filter path.  All values are read-only and pinned to the
    supported executable.
    """
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        mode = read_exact(fd, module_base + FILTER_THREAD_MODE_RVA, 1)[0]
        thread_a = int.from_bytes(read_exact(fd, module_base + FILTER_THREAD_A_RVA, 8), "little")
        thread_b = int.from_bytes(read_exact(fd, module_base + FILTER_THREAD_B_RVA, 8), "little")
    finally:
        os.close(fd)
    active, alternate = (thread_a, thread_b) if mode else (thread_b, thread_a)
    if not 0 < active <= 0xFFFFFFFF or not 0 < alternate <= 0xFFFFFFFF or active == alternate:
        raise DiscoverabilityError("full-filter thread globals are invalid or ambiguous")
    return alternate, {"mode": mode, "activeThread": active, "selectedThread": alternate}


def run(
    pid: int,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    sample_only: bool = False,
    with_names: bool = False,
    device: Any | None = None,
    frida_api: Any | None = None,
    remote_address: str | None = None,
    remote_process: str = "fm.exe",
    use_latest_observed_context: bool = False,
) -> dict[str, Any]:
    """Execute the source-builder then full-filter Frida experiment."""
    before, arguments, before_ids = _live_context(pid)
    manager = _active_manager(before)
    module_base = int(before.module_base, 0)
    source, manager_interface, team = arguments
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION, "researchOnly": True,
        "adapter": "fm20-frida-discoverability", "status": "started",
        "createdAt": datetime.now(UTC).isoformat(), "pid": pid,
        "buildProfile": before.profile, "gameDate": before.game_date,
        "activeManagerId": manager.id, "managedClub": {"id": manager.club.id, "name": manager.club.name},
        "managerRooted": True, "sourcePointer": hex(source),
        "managerSearchInterface": hex(manager_interface), "managedTeamPointer": hex(team),
        "sourceCountBeforeRebuild": len(before_ids), "chunkSize": chunk_size,
        "sampleOnly": sample_only, "packageEvidence": "not natively decoded",
    }
    expected_base = int(preflight(pid)["moduleBase"], 0)
    if expected_base != module_base:
        raise DiscoverabilityError("probe and Frida preflight module bases differ")
    if frida_api is None:
        try:
            frida_api = importlib.import_module("frida")
        except ImportError as error:
            raise DiscoverabilityError("Frida is not installed; run with `uv run --extra research`") from error
    if device is None:
        if remote_address is None:
            raise DiscoverabilityError("a controller-owned Windows Frida server address is required")
        device = frida_api.get_device_manager().add_remote_device(remote_address)
    matches = [process for process in device.enumerate_processes() if process.name.casefold() == remote_process.casefold()]
    if len(matches) != 1:
        raise DiscoverabilityError(f"expected one remote {remote_process!r} process, found {len(matches)}")
    report["transport"] = {"kind": "windows-frida-server", "address": remote_address, "process": remote_process, "targetPid": matches[0].pid}

    runtime_context = runtime_thread = None
    if use_latest_observed_context:
        runtime_context, runtime_thread, observation_path = latest_observed_context(pid, module_base, source)
        report["observedPlayerSearchContext"] = hex(runtime_context)
        report["observedPlayerSearchThread"] = runtime_thread
        report["observedPlayerSearchReport"] = str(observation_path)
        report["builderCapture"] = {"skipped": "using current Player Search source and observed runtime context"}
        rebuilt, rebuilt_arguments, source_ids = before, arguments, before_ids
    else:
        builder_capture = extract(device, matches[0].pid, builder_agent_source(before.module_base, arguments), script_name="fm20-discoverability-builder")
        report["builderCapture"] = builder_capture
        if not (
            builder_capture["attached"] and builder_capture["agentReady"] and builder_capture["builderReturnValue"] is not None
            and builder_capture["scriptUnloaded"] and builder_capture["detached"] and not builder_capture["agentErrors"]
        ):
            _raise_with_report(report, "Frida search-source builder did not complete cleanly")
        rebuilt, rebuilt_arguments, source_ids = _live_context(pid)
        if rebuilt_arguments != arguments:
            raise DiscoverabilityError("manager-rooted search arguments changed after Frida builder")
    filter_object, records, knowledge_context = _record_context(pid, module_base, source, manager.id)
    if runtime_context is not None and runtime_thread is not None:
        filter_thread = runtime_thread
        filter_thread_state = {"selection": "observed-player-search-thread", "selectedThread": filter_thread}
    else:
        filter_thread, filter_thread_state = resolve_filter_thread(pid, module_base)
    if sorted(records) != sorted(source_ids):
        raise DiscoverabilityError("source records disagree with manager-rooted source IDs")
    squad = [
        (int(player.id), player.contract.contracted_club.id if player.contract and player.contract.contracted_club else None)
        for player in rebuilt.first_team_squad
    ]
    own_ids = own_contracted_ids(squad, manager.club.id)
    rows, sample_count = filter_order(records, own_ids)
    if sample_only:
        rows = rows[:sample_count]
    filter_capture = extract(
        device, matches[0].pid,
        filter_agent_source(before.module_base, filter_object=filter_object, manager_interface=manager_interface,
                            team=team, knowledge_context=knowledge_context, rows=rows,
                            sample_count=sample_count, chunk_size=chunk_size, thread_id=filter_thread,
                            runtime_context=runtime_context,
                            enforce_sample=not use_latest_observed_context),
        script_name="fm20-discoverability-filter",
    )
    report["filterCapture"] = filter_capture
    if not (
        filter_capture["attached"] and filter_capture["agentReady"] and filter_capture["scriptUnloaded"]
        and filter_capture["detached"] and not filter_capture["agentErrors"]
    ):
        _raise_with_report(report, "Frida full-filter batch did not complete cleanly")
    try:
        evaluations = decode_filter_capture(rows, filter_capture)
    except DiscoverabilityError as error:
        error.report = report
        raise
    after, after_arguments, after_source_ids = _live_context(pid)
    report.update({
        "sourceCount": len(records), "filterObject": hex(filter_object), "knowledgeContext": hex(knowledge_context),
        "filterThreadState": filter_thread_state,
        "sameActiveManager": manager.id == _active_manager(after).id,
        "sameGameDate": before.game_date == after.game_date,
        "sameNativeArguments": arguments == after_arguments,
        "sameSourceIdsAfterFilter": sorted(source_ids) == sorted(after_source_ids),
        "processAliveAfterDetach": process_alive(pid),
    })
    if sample_only:
        report["sampleResults"] = {str(player_id): evaluations[player_id] for player_id in sorted(evaluations)}
        report["sampleMismatches"] = filter_capture.get("sampleMismatches", [])
        report["passed"] = all((report["sameActiveManager"], report["sameGameDate"], report["sameNativeArguments"], report["sameSourceIdsAfterFilter"], report["processAliveAfterDetach"]))
    else:
        report.update(summarize(list(records), evaluations, True, own_ids))
        report["passed"] = all((report["sameActiveManager"], report["sameGameDate"], report["sameNativeArguments"], report["sameSourceIdsAfterFilter"], report["processAliveAfterDetach"], report["allOwnFirstTeamExcluded"]))
        if with_names and report["discoverablePlayerIds"] is not None:
            names = resolve_player_names(pid, report["discoverablePlayerIds"])
            report["discoverablePlayers"] = [{"id": player_id, "name": names.get(player_id)} for player_id in report["discoverablePlayerIds"]]
    report["status"] = "complete" if report["passed"] else "failed"
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--module-base", required=True)
    parser.add_argument("--remote-address", required=True)
    parser.add_argument("--remote-process", default="fm.exe")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--with-names", action="store_true")
    parser.add_argument("--use-latest-observed-context", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report: dict[str, Any]
    status = 1
    try:
        pid = choose_pid(args.pid)
        expected_base = int(args.module_base, 0)
        actual_base = int(preflight(pid)["moduleBase"], 0)
        if expected_base != actual_base:
            raise DiscoverabilityError("controller and adapter module bases differ")
        report = run(pid, chunk_size=args.chunk_size, sample_only=args.sample_only,
                     with_names=args.with_names, remote_address=args.remote_address,
                     remote_process=args.remote_process,
                     use_latest_observed_context=args.use_latest_observed_context)
        phases = [report.get("filterCapture", {})] if args.use_latest_observed_context else [report.get("builderCapture", {}), report.get("filterCapture", {})]
        report["capture"] = {
            "attached": all(phase.get("attached") for phase in phases),
            "agentReady": all(phase.get("agentReady") for phase in phases),
            "scriptUnloaded": all(phase.get("scriptUnloaded") for phase in phases),
            "detached": all(phase.get("detached") for phase in phases),
        }
        report["capture"]["fridaVersion"] = str(importlib.import_module("frida").__version__)
        status = 0 if report["status"] == "complete" else 1
    except (DiscoverabilityError, FridaTraceError, ProbeError, OSError, ValueError, TimeoutError) as error:
        partial = getattr(error, "report", None)
        report = partial if isinstance(partial, dict) else {
            "schemaVersion": SCHEMA_VERSION, "researchOnly": True,
            "adapter": "fm20-frida-discoverability",
        }
        report.update({
            "status": "failed", "error": f"{type(error).__name__}: {error}",
            "processAliveAfterDetach": process_alive(args.pid) if args.pid else None,
        })
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(f"RESULT {args.report} status={report['status']} source={report.get('sourceCount', 0)} discoverable={report.get('discoverableCount', 0)}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())

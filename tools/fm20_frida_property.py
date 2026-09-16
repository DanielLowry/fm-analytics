#!/usr/bin/env python3
"""Cold, manager-visible property reads through FM20's own property getter.

Research-only adapter launched by ``tools/fm20_research.py``. It resolves the
managed first-team squad from read-only process memory, then uses the
controller-owned Windows Frida server to call FM's person property getter
(virtual slot 0x10 on the ``ACTUAL_PLAYER`` person interface) for each player.
The calls run on FM's busiest UI thread, from inside a QueryPerformanceCounter
hook, so FM's own thread executes them. Only FM's visible category is reported;
the underlying foot ratings are never sent out of FM.
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

from tools.fm20_frida_trace import FridaTraceError, preflight, process_alive
from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    read_exact,
    read_fm_string,
    read_human_manager_contexts,
    read_i32,
    read_u64,
)


SCHEMA_VERSION = 1
MAX_PEOPLE = 64
AGENT_TIMEOUT_SECONDS = 20.0
PERSON_PROPERTY_SLOT = 0x10
TYPE_TABLE_RVA = 0x3F628F0
LABEL_MAPPER_RVA = 0x522E720
STRING_RELEASE_RVA = 0x3F5D4E0
FOOT_KEY = 0x50666F74  # 'tofP': record holding the two foot sub-properties
LEFT_FOOT_KEY = 0x506C6647  # 'GflP'
RIGHT_FOOT_KEY = 0x50726647  # 'GfrP'
# Text returned live by FM's own label mapper (RVA 0x522e720) for each index.
FOOTEDNESS_LABELS = {0: "Left Only", 1: "Left", 2: "Right Only", 3: "Right", 4: "Either"}
SUPPORTED_FIELDS = ("footedness",)


class PropertyReadError(RuntimeError):
    """A cold property read failed its bounded safety or evidence checks."""


def four_cc(value: int) -> str:
    """Render an FM property key the way it appears in executable bytes."""
    return value.to_bytes(4, "little").decode("ascii")


def read_owned_people(memory_fd: int, module_base: int) -> list[dict[str, str]]:
    """Resolve managed first-team person interfaces using the proven probe layout."""
    contexts = [context for context in read_human_manager_contexts(memory_fd, module_base) if context.manager.active]
    if len(contexts) != 1 or not contexts[0].team_address:
        raise PropertyReadError("expected exactly one active manager with a first team")
    team = contexts[0].team_address
    if read_exact(memory_fd, team + 0x30, 1) != b"\x00":
        raise PropertyReadError("active manager contract does not point to a first team")
    start = read_u64(memory_fd, team + 0x38)
    end = read_u64(memory_fd, team + 0x40)
    if start == 0 or end < start or (end - start) % 8 != 0:
        raise PropertyReadError(f"invalid squad bounds 0x{start:x}-0x{end:x}")
    count = (end - start) // 8
    if count > MAX_PEOPLE:
        raise PropertyReadError(f"implausible first-team squad size {count}")
    expected_vtable = module_base + FM20_4_4_STEAM.player_type_offset
    people: list[dict[str, str]] = []
    for index in range(count):
        try:
            person = read_u64(memory_fd, start + index * 8) + 0x8 + 0x1C0
            if read_u64(memory_fd, person) != expected_vtable:
                continue
            actual = person + 0x28
            name = " ".join(
                part
                for part in (read_fm_string(memory_fd, actual + 0x30), read_fm_string(memory_fd, actual + 0x38))
                if part
            )
            people.append({"id": str(read_i32(memory_fd, person + 0xC)), "name": name, "address": f"0x{person:x}"})
        except (OSError, ProbeError):
            continue
    if not people:
        raise PropertyReadError("managed first team contains no readable players")
    return people


AGENT_TEMPLATE = r"""
'use strict';
const config = __CONFIG__;
const fm = Process.getModuleByName('fm.exe');
if (!fm.base.equals(ptr(config.moduleBase))) {
  send({kind: 'error', error: 'FM module base differs from preflight'});
  throw new Error('FM module base differs from preflight');
}
const inFm = address => address.compare(fm.base) >= 0 && address.compare(fm.base.add(fm.size)) < 0;
const personVtable = fm.base.add(config.personVtableRva);
const typeTable = new NativeFunction(fm.base.add(config.typeTableRva), 'pointer', []);
const labelMapper = new NativeFunction(fm.base.add(config.labelMapperRva), 'pointer', ['pointer', 'int32', 'uint8']);
const releaseString = new NativeFunction(fm.base.add(config.stringReleaseRva), 'void', ['pointer']);

function virtualSlot(object, offset) {
  const fn = object.readPointer().add(offset).readPointer();
  if (!inFm(fn)) throw new Error('virtual slot resolves outside fm.exe');
  return fn;
}
function footCategory(left, right) {
  // FOOT_LABEL value handler (RVA 0x5551cd0) boundaries.
  if (left <= 0 || right <= 0) return 'unknown';
  if (left >= 15) return right < 8 ? 0 : (right < 15 ? 1 : 4);
  return left >= 8 ? 3 : 2;
}
function readFootCategory(person) {
  if (!person.readPointer().equals(personVtable)) throw new Error('person interface vtable mismatch');
  const getter = new NativeFunction(virtualSlot(person, config.propertySlot), 'uint8', ['pointer', 'uint32', 'pointer']);
  const variant = Memory.alloc(16);
  variant.writePointer(typeTable().add(8));
  variant.add(8).writeU64(0);
  try {
    if (!getter(person, config.footKey, variant)) return {found: false};
    const type = variant.readPointer();
    const record = new NativeFunction(virtualSlot(type, 0x78), 'pointer', ['pointer', 'pointer', 'uint32'])(type, variant, 0);
    const begin = record.readPointer();
    const size = record.add(8).readPointer().sub(begin).toInt32();
    if (size < 0 || size % 16 !== 0 || size > 16 * 16) throw new Error('implausible property record size');
    const ratings = {};
    for (let offset = 0; offset < size; offset += 16) {
      const key = begin.add(offset).readU32();
      if (key !== config.leftKey && key !== config.rightKey) continue;
      const value = begin.add(offset + 8).readPointer();
      const valueType = value.readPointer();
      ratings[key] = new NativeFunction(virtualSlot(valueType, 0x30), 'int8', ['pointer', 'pointer'])(valueType, value);
    }
    if (!(config.leftKey in ratings) || !(config.rightKey in ratings)) return {found: true, category: 'missing-subkey'};
    return {found: true, category: footCategory(ratings[config.leftKey], ratings[config.rightKey])};
  } finally {
    const type = variant.readPointer();
    new NativeFunction(virtualSlot(type, 0x8), 'void', ['pointer', 'pointer'])(type, variant);
  }
}
function labelText(index) {
  const out = Memory.alloc(8);
  out.writePointer(ptr(0));
  labelMapper(out, index, 0);
  try {
    const text = out.readPointer();
    if (text.isNull()) return null;
    const length = text.readS32();
    return length > 0 && length < 256 ? text.add(4).readUtf8String(length) : null;
  } finally {
    releaseString(out);
  }
}
function runOnce() {
  const players = [];
  for (const person of config.people) {
    try {
      players.push({id: person.id, ...readFootCategory(ptr(person.address))});
    } catch (error) {
      players.push({id: person.id, error: String(error)});
    }
  }
  send({kind: 'players', players});
  const labels = {};
  for (const index of config.labelIndexes) {
    try {
      labels[index] = labelText(index);
    } catch (error) {
      labels[index] = null;
      send({kind: 'label-error', index, error: String(error)});
    }
  }
  send({kind: 'labels', labels});
}

const qpc = Module.findGlobalExportByName('QueryPerformanceCounter');
if (qpc === null) {
  send({kind: 'error', error: 'QueryPerformanceCounter export not found'});
  throw new Error('QueryPerformanceCounter export not found');
}
send({kind: 'ready', moduleBase: fm.base.toString(), people: config.people.length});
const sample = {};
const sampler = Interceptor.attach(qpc, {onEnter() {
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
  send({kind: 'thread', thread, sample});
  let state = 'armed';
  const runner = Interceptor.attach(qpc, {onEnter() {
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


def build_agent_source(module_base: str, people: Sequence[dict[str, str]]) -> str:
    if not 1 <= len(people) <= MAX_PEOPLE:
        raise PropertyReadError(f"person count must be from 1 to {MAX_PEOPLE}")
    for person in people:
        if int(person["address"], 16) <= 0:
            raise PropertyReadError("person address must be positive")
    config = {
        "moduleBase": module_base,
        "personVtableRva": FM20_4_4_STEAM.player_type_offset,
        "propertySlot": PERSON_PROPERTY_SLOT,
        "typeTableRva": TYPE_TABLE_RVA,
        "labelMapperRva": LABEL_MAPPER_RVA,
        "stringReleaseRva": STRING_RELEASE_RVA,
        "footKey": FOOT_KEY,
        "leftKey": LEFT_FOOT_KEY,
        "rightKey": RIGHT_FOOT_KEY,
        "labelIndexes": sorted(FOOTEDNESS_LABELS),
        "threadSampleMs": 1000,
        "people": [{"id": person["id"], "address": person["address"]} for person in people],
    }
    return AGENT_TEMPLATE.replace("__CONFIG__", json.dumps(config))


def extract(device: Any, target_pid: int, source: str, *, timeout_seconds: float = AGENT_TIMEOUT_SECONDS) -> dict[str, Any]:
    finished = threading.Event()
    result: dict[str, Any] = {
        "attached": False,
        "agentReady": False,
        "thread": None,
        "players": [],
        "labels": {},
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
            result["thread"] = {"id": payload.get("thread"), "qpcSample": payload.get("sample")}
        elif kind == "players":
            result["players"] = payload.get("players", [])
        elif kind == "labels":
            result["labels"] = payload.get("labels", {})
        elif kind == "label-error":
            result["agentErrors"].append({"kind": "label-error", "description": payload.get("error")})
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
        script = session.create_script(source, name="fm20-property-read")
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


def summarize_footedness(people: Sequence[dict[str, str]], capture: dict[str, Any]) -> dict[str, Any]:
    labels = {str(index): text for index, text in capture.get("labels", {}).items()}
    labels_verified = all(labels.get(str(index)) == text for index, text in FOOTEDNESS_LABELS.items())
    rows_by_id = {row.get("id"): row for row in capture.get("players", []) if isinstance(row, dict)}
    players = []
    resolved = 0
    for person in people:
        row = rows_by_id.get(person["id"], {})
        category = row.get("category")
        value = None
        if row.get("error"):
            status = "error"
        elif not row.get("found"):
            status = "not-found"
        elif category == "unknown":
            status = "unknown"
        elif isinstance(category, int) and not isinstance(category, bool) and category in FOOTEDNESS_LABELS and labels_verified:
            status = "visible"
            value = FOOTEDNESS_LABELS[category]
            resolved += 1
        else:
            status = "unverified-category"
        entry = {"id": person["id"], "name": person["name"], "footedness": value, "status": status}
        if row.get("error"):
            entry["error"] = row["error"]
        players.append(entry)
    return {
        "field": "footedness",
        "scope": "managed-first-team",
        "source": "FM person property getter 'tofP' with FOOT_LABEL boundaries",
        "requestedCount": len(people),
        "resolvedCount": resolved,
        "labelsVerified": labels_verified,
        "fmLabels": labels,
        "players": players,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--module-base", required=True)
    parser.add_argument("--remote-address", required=True, help="controller-owned Windows Frida server address")
    parser.add_argument("--remote-process", default="fm.exe")
    parser.add_argument("--field", action="append", choices=SUPPORTED_FIELDS)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fields = args.field or list(SUPPORTED_FIELDS)
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "researchOnly": True,
        "adapter": "fm20-frida-property",
        "createdAt": datetime.now(UTC).isoformat(),
        "status": "started",
        "fields": fields,
        "safety": "guarded-native-call",
    }
    status = 1
    try:
        expected_base = int(args.module_base, 0)
        before = preflight(args.pid)
        if int(before["moduleBase"], 0) != expected_base:
            raise PropertyReadError("controller and adapter module bases differ")
        report["preflight"] = before
        memory_fd = os.open(f"/proc/{args.pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
        try:
            people = read_owned_people(memory_fd, expected_base)
        finally:
            os.close(memory_fd)
        report["scope"] = {"kind": "managed-first-team", "playerCount": len(people)}
        try:
            frida_api = importlib.import_module("frida")
        except ImportError as error:
            raise PropertyReadError("Frida is not installed; run with `uv run --extra research`") from error
        try:
            device = frida_api.get_device_manager().add_remote_device(args.remote_address)
            matches = [
                process
                for process in device.enumerate_processes()
                if process.name.casefold() == args.remote_process.casefold()
            ]
        except Exception as error:
            raise PropertyReadError(
                f"cannot connect to Windows Frida server: {type(error).__name__}: {error}"
            ) from error
        if len(matches) != 1:
            raise PropertyReadError(f"expected one remote {args.remote_process!r} process, found {len(matches)}")
        report["transport"] = {
            "kind": "windows-frida-server",
            "address": args.remote_address,
            "process": args.remote_process,
            "targetPid": matches[0].pid,
        }
        capture_result = extract(device, matches[0].pid, build_agent_source(before["moduleBase"], people))
        report["capture"] = {key: value for key, value in capture_result.items() if key not in {"players", "labels"}}
        report["capture"]["fridaVersion"] = str(frida_api.__version__)
        report["extraction"] = summarize_footedness(people, capture_result)
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
            raise PropertyReadError(f"Frida property read did not complete cleanly: {detail}")
        if not report["extraction"]["labelsVerified"]:
            raise PropertyReadError("FM's label mapper did not return the registered footedness labels")
        report["status"] = "complete"
        status = 0
    except (PropertyReadError, FridaTraceError, ProbeError, OSError, ValueError) as error:
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

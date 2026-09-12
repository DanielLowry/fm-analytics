#!/usr/bin/env python3
"""Capture only manager-visible FM20 attribute render results.

This is a bounded research harness for the supported FM20 build. It attaches
GDB, observes the pre-format render boundary, reads exactly two visible bytes,
and detaches after the configured duration. Captures are event samples, not a
claim that every discoverable player or cached cell was observed.
"""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Callable, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fm_analytics.bridge.visibility_result import decode_visible_bound_bytes
from fm_analytics.domain.models import AttributeObservation
from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    parse_module_mapping,
    validate_executable,
)
from tools.fm20_visibility_trace import (
    ATTRIBUTE_OFFSETS,
    VISIBILITY_RESULT_RVA,
    display_attribute_id,
)


EVENT_PREFIX = "FMVIS_EVENT "
ERROR_PREFIX = "FMVIS_ERROR "
HIT_PREFIX = "FMVIS_HIT "
KNOWLEDGE_PREFIX = "FMVIS_KNOWLEDGE "
KNOWLEDGE_DECISION_PREFIX = "FMVIS_KNOWLEDGE_DECISION "
IDENTITY_PREFIX = "FMVIS_IDENTITY "
REPLAY_PREFIX = "FMVIS_REPLAY "
READY_LINE = "FMVIS_READY"
GDB_SCRIPT = Path(__file__).with_suffix(".gdb")
ATTACH_TIMEOUT_SECONDS = 20.0
DETACH_TIMEOUT_SECONDS = 8.0
KNOWLEDGE_RESULT_RVA = 0x15A51C3
KNOWLEDGE_CONTEXT_ENTRY_RVA = 0x15A4DC0
KNOWLEDGE_DECISION_ENTRY_RVA = 0x15A51B5
KNOWLEDGE_DECISION_MERGE_RVA = 0x15A51DC
KNOWLEDGE_DECISION_RESULT_RVA = 0x15A52B5
VISIBLE_RESULT_BUILDER_RVA = 0x15A4A90

ATTRIBUTE_NAMES_BY_ID = {
    display_attribute_id(name): name for name in ATTRIBUTE_OFFSETS
}


class CaptureError(RuntimeError):
    """The bounded render capture could not complete safely."""


@dataclass(frozen=True)
class VisibleCaptureEvent:
    player_id: str
    attribute: str
    attribute_id: str
    observation: AttributeObservation

    def to_dict(self) -> dict[str, object]:
        return {
            "playerId": self.player_id,
            "attribute": self.attribute,
            "attributeId": self.attribute_id,
            "observation": self.observation.to_dict(),
        }


@dataclass(frozen=True)
class KnowledgeCacheEvent:
    context_address: str
    context_owner_address: str
    player_id: str | None
    player_row_id: str
    record_address: str | None
    knowledge_level: int | None
    local_entry_count: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "contextAddress": self.context_address,
            "contextOwnerAddress": self.context_owner_address,
            "playerId": self.player_id,
            "playerRowId": self.player_row_id,
            "recordAddress": self.record_address,
            "knowledgeLevel": self.knowledge_level,
            "localEntryCount": self.local_entry_count,
        }


@dataclass(frozen=True)
class KnowledgeDecisionEvent:
    player_id: str
    attribute: str | None
    attribute_id: str
    explicit_knowledge: int
    baseline_knowledge: int
    merged_knowledge: int
    effective_knowledge: int
    range_threshold: int
    exact_threshold: int
    classification: str

    def to_dict(self) -> dict[str, object]:
        return {
            "playerId": self.player_id,
            "attribute": self.attribute,
            "attributeId": self.attribute_id,
            "explicitKnowledge": self.explicit_knowledge,
            "baselineKnowledge": self.baseline_knowledge,
            "mergedKnowledge": self.merged_knowledge,
            "effectiveKnowledge": self.effective_knowledge,
            "rangeThreshold": self.range_threshold,
            "exactThreshold": self.exact_threshold,
            "classification": self.classification,
        }


@dataclass(frozen=True)
class ReplayEvent:
    player_id: str
    attribute: str
    attribute_id: str
    matched: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "playerId": self.player_id,
            "attribute": self.attribute,
            "attributeId": self.attribute_id,
            "matched": self.matched,
        }


@dataclass(frozen=True)
class CaptureResult:
    pid: int
    profile: str
    captured_at: str
    requested_duration_seconds: float
    hook_hit_count: int
    diagnostic_attribute_ids: tuple[str, ...]
    identity_resolution_counts: tuple[tuple[str, int], ...]
    knowledge_cache_events: tuple[KnowledgeCacheEvent, ...]
    knowledge_decision_events: tuple[KnowledgeDecisionEvent, ...]
    replay_events: tuple[ReplayEvent, ...]
    raw_event_count: int
    observations: tuple[VisibleCaptureEvent, ...]
    complete: bool = False
    coverage: str = "render-events-only"

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["requestedDurationSeconds"] = result.pop(
            "requested_duration_seconds"
        )
        result["capturedAt"] = result.pop("captured_at")
        result["rawEventCount"] = result.pop("raw_event_count")
        result["hookHitCount"] = result.pop("hook_hit_count")
        result["diagnosticAttributeIds"] = result.pop(
            "diagnostic_attribute_ids"
        )
        result["identityResolutionCounts"] = dict(
            result.pop("identity_resolution_counts")
        )
        result["knowledgeCacheEvents"] = [
            event.to_dict() for event in self.knowledge_cache_events
        ]
        result.pop("knowledge_cache_events")
        result["knowledgeDecisionEvents"] = [
            event.to_dict() for event in self.knowledge_decision_events
        ]
        result.pop("knowledge_decision_events")
        result["replayEvents"] = [event.to_dict() for event in self.replay_events]
        result.pop("replay_events")
        result["observations"] = [event.to_dict() for event in self.observations]
        return result


class CaptureAccumulator:
    def __init__(self) -> None:
        self.hook_hit_count = 0
        self.diagnostic_attribute_ids: set[int] = set()
        self.raw_event_count = 0
        self._events: dict[tuple[str, str], VisibleCaptureEvent] = {}
        self._knowledge_events: set[KnowledgeCacheEvent] = set()
        self._knowledge_decision_events: set[KnowledgeDecisionEvent] = set()
        self._replay_events: set[ReplayEvent] = set()
        self.identity_resolution_counts: dict[str, int] = {}

    def add(self, event: VisibleCaptureEvent) -> None:
        self.raw_event_count += 1
        key = (event.player_id, event.attribute)
        existing = self._events.get(key)
        if existing is not None and existing != event:
            raise CaptureError(
                "conflicting visible observations for "
                f"player {event.player_id} attribute {event.attribute}"
            )
        self._events.setdefault(key, event)

    def record_hook_hit(self, attribute_id: int) -> None:
        if not 0 <= attribute_id <= 0xFF:
            raise CaptureError("diagnostic attribute ID must be a byte")
        self.hook_hit_count += 1
        self.diagnostic_attribute_ids.add(attribute_id)

    def add_knowledge_event(self, event: KnowledgeCacheEvent) -> None:
        self._knowledge_events.add(event)

    def record_identity_resolution(self, status: str) -> None:
        self.identity_resolution_counts[status] = (
            self.identity_resolution_counts.get(status, 0) + 1
        )

    def add_knowledge_decision(self, event: KnowledgeDecisionEvent) -> None:
        self._knowledge_decision_events.add(event)

    def add_replay(self, event: ReplayEvent) -> None:
        if not event.matched:
            raise CaptureError(
                "direct visible-result replay disagreed with FM's original result"
            )
        self._replay_events.add(event)

    def validate_knowledge_alignment(self) -> None:
        classifications: dict[tuple[str, str], set[str]] = {}
        for event in self._knowledge_decision_events:
            key = (event.player_id, event.attribute_id)
            classifications.setdefault(key, set()).add(event.classification)
        for event in self._events.values():
            key = (event.player_id, event.attribute_id)
            matching = classifications.get(key)
            if not matching:
                raise CaptureError(
                    "visible observation has no matching knowledge decision for "
                    f"player {event.player_id} attribute {event.attribute_id}"
                )
            if matching != {event.observation.visibility.value}:
                raise CaptureError(
                    "knowledge classification disagrees with visible observation for "
                    f"player {event.player_id} attribute {event.attribute_id}"
                )

    @property
    def observations(self) -> tuple[VisibleCaptureEvent, ...]:
        return tuple(
            sorted(
                self._events.values(),
                key=lambda event: (int(event.player_id), event.attribute),
            )
        )

    @property
    def knowledge_events(self) -> tuple[KnowledgeCacheEvent, ...]:
        return tuple(
            sorted(
                self._knowledge_events,
                key=lambda event: (
                    event.context_address,
                    int(event.player_row_id),
                    event.record_address or "",
                ),
            )
        )

    @property
    def knowledge_decision_events(self) -> tuple[KnowledgeDecisionEvent, ...]:
        return tuple(
            sorted(
                self._knowledge_decision_events,
                key=lambda event: (
                    int(event.player_id),
                    int(event.attribute_id, 0),
                    event.explicit_knowledge,
                    event.baseline_knowledge,
                    event.effective_knowledge,
                ),
            )
        )

    @property
    def replay_events(self) -> tuple[ReplayEvent, ...]:
        return tuple(
            sorted(
                self._replay_events,
                key=lambda event: (int(event.player_id), event.attribute),
            )
        )


def parse_event_line(line: str) -> VisibleCaptureEvent | None:
    if not line.startswith(EVENT_PREFIX):
        return None
    try:
        raw = json.loads(line.removeprefix(EVENT_PREFIX))
    except json.JSONDecodeError as exc:
        raise CaptureError(f"invalid GDB event JSON: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "attribute_id",
        "lower",
        "player_id",
        "upper",
    }:
        raise CaptureError("GDB event has an unexpected field contract")
    player_id = _required_int(raw, "player_id")
    attribute_id = _required_int(raw, "attribute_id")
    attribute = ATTRIBUTE_NAMES_BY_ID.get(attribute_id)
    if attribute is None:
        raise CaptureError(f"unsupported display attribute ID 0x{attribute_id:02x}")
    try:
        observation = decode_visible_bound_bytes(
            _required_int(raw, "lower"),
            _required_int(raw, "upper"),
        )
    except ValueError as exc:
        raise CaptureError(f"invalid visible result: {exc}") from exc
    return VisibleCaptureEvent(
        player_id=str(player_id),
        attribute=attribute,
        attribute_id=f"0x{attribute_id:02x}",
        observation=observation,
    )


def parse_diagnostic_hit(line: str) -> int | None:
    if not line.startswith(HIT_PREFIX):
        return None
    try:
        raw = json.loads(line.removeprefix(HIT_PREFIX))
    except json.JSONDecodeError as exc:
        raise CaptureError(f"invalid diagnostic hit JSON: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"attribute_id"}:
        raise CaptureError("diagnostic hit has an unexpected field contract")
    attribute_id = _required_int(raw, "attribute_id")
    if not 0 <= attribute_id <= 0xFF:
        raise CaptureError("diagnostic attribute ID must be a byte")
    return attribute_id


def parse_knowledge_event(line: str) -> KnowledgeCacheEvent | None:
    if not line.startswith(KNOWLEDGE_PREFIX):
        return None
    try:
        raw = json.loads(line.removeprefix(KNOWLEDGE_PREFIX))
    except json.JSONDecodeError as exc:
        raise CaptureError(f"invalid knowledge event JSON: {exc}") from exc
    required = {
        "context_address",
        "context_owner_address",
        "knowledge_level",
        "local_entry_count",
        "player_id",
        "player_row_id",
        "record_address",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise CaptureError("knowledge event has an unexpected field contract")
    context_address = _required_nonnegative_int(raw, "context_address")
    context_owner_address = _required_nonnegative_int(
        raw, "context_owner_address"
    )
    player_id = _optional_nonnegative_int(raw, "player_id")
    player_row_id = _required_nonnegative_int(raw, "player_row_id")
    record_address = _required_nonnegative_int(raw, "record_address")
    knowledge_level = _optional_bounded_int(raw, "knowledge_level", 0, 100)
    local_entry_count = _optional_bounded_int(
        raw, "local_entry_count", 0, 1_000_000
    )
    if record_address == 0 and knowledge_level is not None:
        raise CaptureError("missing knowledge record cannot have a knowledge level")
    return KnowledgeCacheEvent(
        context_address=hex(context_address),
        context_owner_address=hex(context_owner_address),
        player_id=str(player_id) if player_id is not None else None,
        player_row_id=str(player_row_id),
        record_address=hex(record_address) if record_address else None,
        knowledge_level=knowledge_level,
        local_entry_count=local_entry_count,
    )


def parse_identity_resolution(line: str) -> str | None:
    if not line.startswith(IDENTITY_PREFIX):
        return None
    try:
        raw = json.loads(line.removeprefix(IDENTITY_PREFIX))
    except json.JSONDecodeError as exc:
        raise CaptureError(f"invalid identity event JSON: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"offset", "status"}:
        raise CaptureError("identity event has an unexpected field contract")
    status = raw.get("status")
    offset = raw.get("offset")
    if not isinstance(status, str) or status not in {
        "direct-player",
        "direct-person",
        "direct-actual-person",
        "interface-person",
        "unresolved",
    }:
        raise CaptureError("identity event has an unsupported status")
    if status == "interface-person":
        if type(offset) is not int or not -0x10000 <= offset <= 0x10000:
            raise CaptureError("interface identity requires a bounded adjustment")
    elif offset is not None:
        raise CaptureError("non-wrapper identity cannot have an offset")
    if offset is None:
        return status
    sign = "-" if offset < 0 else "+"
    return f"{status}@{sign}0x{abs(offset):x}"


def parse_knowledge_decision(line: str) -> KnowledgeDecisionEvent | None:
    if not line.startswith(KNOWLEDGE_DECISION_PREFIX):
        return None
    try:
        raw = json.loads(line.removeprefix(KNOWLEDGE_DECISION_PREFIX))
    except json.JSONDecodeError as exc:
        raise CaptureError(f"invalid knowledge decision JSON: {exc}") from exc
    required = {
        "attribute_id",
        "baseline_knowledge",
        "classification",
        "effective_knowledge",
        "exact_threshold",
        "explicit_knowledge",
        "merged_knowledge",
        "player_id",
        "range_threshold",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise CaptureError("knowledge decision has an unexpected field contract")
    player_id = _required_nonnegative_int(raw, "player_id")
    attribute_id = _required_bounded_int(raw, "attribute_id", 0, 0xFF)
    explicit = _required_bounded_int(raw, "explicit_knowledge", 0, 100)
    baseline = _required_bounded_int(raw, "baseline_knowledge", 0, 100)
    merged = _required_bounded_int(raw, "merged_knowledge", 0, 100)
    effective = _required_bounded_int(raw, "effective_knowledge", 0, 100)
    range_threshold = _required_bounded_int(raw, "range_threshold", 1, 100)
    exact_threshold = _required_bounded_int(raw, "exact_threshold", 1, 100)
    classification = raw.get("classification")
    if classification not in {"unknown", "range", "known"}:
        raise CaptureError("knowledge decision has an invalid classification")
    if merged != max(explicit, baseline):
        raise CaptureError("merged knowledge does not match FM's merge rule")
    if effective < merged:
        raise CaptureError("effective knowledge cannot be below merged knowledge")
    expected_classification = (
        "known"
        if effective >= exact_threshold
        else "range"
        if effective >= range_threshold
        else "unknown"
    )
    if classification != expected_classification:
        raise CaptureError("knowledge classification does not match thresholds")
    return KnowledgeDecisionEvent(
        player_id=str(player_id),
        attribute=ATTRIBUTE_NAMES_BY_ID.get(attribute_id),
        attribute_id=f"0x{attribute_id:02x}",
        explicit_knowledge=explicit,
        baseline_knowledge=baseline,
        merged_knowledge=merged,
        effective_knowledge=effective,
        range_threshold=range_threshold,
        exact_threshold=exact_threshold,
        classification=classification,
    )


def parse_replay_event(line: str) -> ReplayEvent | None:
    if not line.startswith(REPLAY_PREFIX):
        return None
    try:
        raw = json.loads(line.removeprefix(REPLAY_PREFIX))
    except json.JSONDecodeError as exc:
        raise CaptureError(f"invalid replay JSON: {exc}") from exc
    required = {"attribute_id", "matched", "player_id"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise CaptureError("replay event has an unexpected field contract")
    player_id = _required_nonnegative_int(raw, "player_id")
    attribute_id = _required_bounded_int(raw, "attribute_id", 0, 0xFF)
    matched = raw.get("matched")
    if type(matched) is not bool:
        raise CaptureError("replay matched flag must be boolean")
    attribute = ATTRIBUTE_NAMES_BY_ID.get(attribute_id)
    if attribute is None:
        raise CaptureError(f"replay used unsupported attribute ID 0x{attribute_id:02x}")
    return ReplayEvent(
        player_id=str(player_id),
        attribute=attribute,
        attribute_id=f"0x{attribute_id:02x}",
        matched=matched,
    )


def build_gdb_environment(
    base_environment: dict[str, str],
    module_base: int,
    attributes: Sequence[str],
    player_ids: Sequence[int],
    *,
    diagnostic_hits: bool = False,
    trace_knowledge_cache: bool = False,
    trace_knowledge_decision: bool = False,
    replay_same_cell: bool = False,
) -> dict[str, str]:
    environment = dict(base_environment)
    environment["FMVIS_BREAKPOINT"] = hex(module_base + VISIBILITY_RESULT_RVA)
    environment["FMVIS_MODULE_BASE"] = hex(module_base)
    environment["FMVIS_ATTRIBUTE_IDS"] = ",".join(
        hex(display_attribute_id(attribute)) for attribute in attributes
    )
    environment["FMVIS_PLAYER_IDS"] = ",".join(str(item) for item in player_ids)
    environment["FMVIS_DIAGNOSTIC_HITS"] = "1" if diagnostic_hits else "0"
    environment["FMVIS_TRACE_KNOWLEDGE_CACHE"] = (
        "1" if trace_knowledge_cache else "0"
    )
    environment["FMVIS_KNOWLEDGE_BREAKPOINT"] = hex(
        module_base + KNOWLEDGE_RESULT_RVA
    )
    environment["FMVIS_TRACE_KNOWLEDGE_DECISION"] = (
        "1" if trace_knowledge_decision else "0"
    )
    environment["FMVIS_KNOWLEDGE_CONTEXT_ENTRY_BREAKPOINT"] = hex(
        module_base + KNOWLEDGE_CONTEXT_ENTRY_RVA
    )
    environment["FMVIS_KNOWLEDGE_DECISION_ENTRY_BREAKPOINT"] = hex(
        module_base + KNOWLEDGE_DECISION_ENTRY_RVA
    )
    environment["FMVIS_KNOWLEDGE_DECISION_MERGE_BREAKPOINT"] = hex(
        module_base + KNOWLEDGE_DECISION_MERGE_RVA
    )
    environment["FMVIS_KNOWLEDGE_DECISION_RESULT_BREAKPOINT"] = hex(
        module_base + KNOWLEDGE_DECISION_RESULT_RVA
    )
    environment["FMVIS_VISIBLE_RESULT_BUILDER_BREAKPOINT"] = hex(
        module_base + VISIBLE_RESULT_BUILDER_RVA
    )
    environment["FMVIS_REPLAY_SAME_CELL"] = "1" if replay_same_cell else "0"
    return environment


def capture(
    pid: int,
    *,
    duration_seconds: float,
    attributes: Sequence[str],
    player_ids: Sequence[int] = (),
    gdb_executable: str = "gdb",
    proc_root: Path = Path("/proc"),
    ready_callback: Callable[[], None] | None = None,
    diagnostic_hits: bool = False,
    trace_knowledge_cache: bool = False,
    trace_knowledge_decision: bool = False,
    replay_same_cell: bool = False,
) -> CaptureResult:
    if duration_seconds <= 0:
        raise CaptureError("capture duration must be positive")
    if not attributes:
        raise CaptureError("at least one attribute is required")
    if not GDB_SCRIPT.is_file():
        raise CaptureError(f"GDB capture script is missing: {GDB_SCRIPT}")

    module_base = _validated_module_base(pid, proc_root)
    environment = build_gdb_environment(
        os.environ,
        module_base,
        tuple(dict.fromkeys(attributes)),
        tuple(dict.fromkeys(player_ids)),
        diagnostic_hits=diagnostic_hits,
        trace_knowledge_cache=trace_knowledge_cache,
        trace_knowledge_decision=trace_knowledge_decision,
        replay_same_cell=replay_same_cell,
    )
    command = [
        gdb_executable,
        "-q",
        "-nx",
        "-ex",
        "set pagination off",
        "-ex",
        "set confirm off",
        "-ex",
        "set print thread-events off",
        "-ex",
        "handle SIGUSR1 nostop noprint pass",
        "-ex",
        f"source {GDB_SCRIPT}",
        "-p",
        str(pid),
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

    accumulator = CaptureAccumulator()
    reader = _LineReader(process)
    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    pending_error: CaptureError | None = None
    try:
        _wait_until_ready(process, reader)
        if ready_callback is not None:
            ready_callback()
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
            knowledge_event = parse_knowledge_event(line)
            if knowledge_event is not None:
                accumulator.add_knowledge_event(knowledge_event)
                continue
            knowledge_decision = parse_knowledge_decision(line)
            if knowledge_decision is not None:
                accumulator.add_knowledge_decision(knowledge_decision)
                continue
            replay_event = parse_replay_event(line)
            if replay_event is not None:
                accumulator.add_replay(replay_event)
                continue
            identity_status = parse_identity_resolution(line)
            if identity_status is not None:
                accumulator.record_identity_resolution(identity_status)
                continue
            diagnostic_attribute_id = parse_diagnostic_hit(line)
            if diagnostic_attribute_id is not None:
                accumulator.record_hook_hit(diagnostic_attribute_id)
                continue
            event = parse_event_line(line)
            if event is not None:
                accumulator.add(event)
    except CaptureError as exc:
        pending_error = exc
    finally:
        detach_error = _detach_gdb(process, reader)
    if pending_error is not None:
        raise pending_error
    if detach_error is not None:
        raise detach_error
    _verify_inferior_alive(pid, proc_root)
    if trace_knowledge_decision:
        accumulator.validate_knowledge_alignment()
    return CaptureResult(
        pid=pid,
        profile=FM20_4_4_STEAM.name,
        captured_at=captured_at,
        requested_duration_seconds=duration_seconds,
        hook_hit_count=accumulator.hook_hit_count,
        diagnostic_attribute_ids=tuple(
            f"0x{item:02x}" for item in sorted(accumulator.diagnostic_attribute_ids)
        ),
        identity_resolution_counts=tuple(
            sorted(accumulator.identity_resolution_counts.items())
        ),
        knowledge_cache_events=accumulator.knowledge_events,
        knowledge_decision_events=accumulator.knowledge_decision_events,
        replay_events=accumulator.replay_events,
        raw_event_count=accumulator.raw_event_count,
        observations=accumulator.observations,
    )


class _LineReader:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        if process.stdout is None:
            raise CaptureError("GDB stdout pipe was not created")
        self.process = process
        self.output = process.stdout
        self.buffer = bytearray()
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.output, selectors.EVENT_READ)

    def read_line(self, timeout: float) -> str | None:
        newline = self.buffer.find(b"\n")
        if newline >= 0:
            return self._pop_line(newline)
        if timeout <= 0 or not self.selector.select(timeout):
            return None
        chunk = os.read(self.output.fileno(), 4096)
        if not chunk:
            return None
        self.buffer.extend(chunk)
        newline = self.buffer.find(b"\n")
        return self._pop_line(newline) if newline >= 0 else None

    def _pop_line(self, newline: int) -> str:
        raw = bytes(self.buffer[:newline])
        del self.buffer[: newline + 1]
        return raw.decode("utf-8", errors="replace").rstrip("\r")


def _wait_until_ready(
    process: subprocess.Popen[bytes], reader: _LineReader
) -> None:
    deadline = monotonic() + ATTACH_TIMEOUT_SECONDS
    while monotonic() < deadline:
        line = reader.read_line(deadline - monotonic())
        if line == READY_LINE:
            return
        if line is not None and line.startswith(ERROR_PREFIX):
            raise CaptureError(line.removeprefix(ERROR_PREFIX))
        if process.poll() is not None:
            raise CaptureError(
                f"GDB exited before capture was ready with status {process.returncode}"
            )
    raise CaptureError("timed out while attaching GDB")


def _detach_gdb(
    process: subprocess.Popen[bytes], reader: _LineReader
) -> CaptureError | None:
    if process.poll() is not None:
        reader.selector.close()
        return None
    try:
        process.send_signal(signal.SIGINT)
        if process.stdin is None:
            raise CaptureError("GDB stdin pipe was not created")
        process.stdin.write(b"detach\nquit\n")
        process.stdin.flush()
        process.wait(timeout=DETACH_TIMEOUT_SECONDS)
    except (BrokenPipeError, OSError, subprocess.TimeoutExpired) as exc:
        process.terminate()
        try:
            process.wait(timeout=DETACH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return CaptureError(f"GDB required forced shutdown: {exc}")
    finally:
        reader.selector.close()
    return None


def _validated_module_base(pid: int, proc_root: Path) -> int:
    try:
        with (proc_root / str(pid) / "maps").open(encoding="utf-8") as maps_file:
            module_base, executable = parse_module_mapping(maps_file)
    except OSError as exc:
        raise CaptureError(f"cannot read process {pid} mappings: {exc}") from exc
    try:
        validate_executable(executable)
    except ProbeError as exc:
        raise CaptureError(str(exc)) from exc
    return module_base


def _verify_inferior_alive(pid: int, proc_root: Path) -> None:
    # capture() and this check must run in the same host-visible process
    # context. A restricted namespace may hide a healthy external process.
    process_dir = proc_root / str(pid)
    if not process_dir.is_dir():
        raise CaptureError(
            "FM process exited during or immediately after debugger detachment"
        )


def _required_int(raw: dict[str, object], name: str) -> int:
    value = raw.get(name)
    if type(value) is not int:
        raise CaptureError(f"GDB event field {name} must be an integer")
    return value


def _required_nonnegative_int(raw: dict[str, object], name: str) -> int:
    value = _required_int(raw, name)
    if value < 0:
        raise CaptureError(f"knowledge event field {name} cannot be negative")
    return value


def _optional_bounded_int(
    raw: dict[str, object], name: str, minimum: int, maximum: int
) -> int | None:
    value = raw.get(name)
    if value is None:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        raise CaptureError(
            f"knowledge event field {name} must be between {minimum} and {maximum}"
        )
    return value


def _required_bounded_int(
    raw: dict[str, object], name: str, minimum: int, maximum: int
) -> int:
    value = _required_int(raw, name)
    if not minimum <= value <= maximum:
        raise CaptureError(
            f"knowledge decision field {name} must be between "
            f"{minimum} and {maximum}"
        )
    return value


def _optional_nonnegative_int(
    raw: dict[str, object], name: str
) -> int | None:
    value = raw.get(name)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise CaptureError(
            f"knowledge event field {name} must be a non-negative integer or null"
        )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    from tools.fm20_visibility_capture_cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

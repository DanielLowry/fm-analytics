python
import json
import os
import gdb


EVENT_PREFIX = "FMVIS_EVENT "
ERROR_PREFIX = "FMVIS_ERROR "
HIT_PREFIX = "FMVIS_HIT "
KNOWLEDGE_PREFIX = "FMVIS_KNOWLEDGE "
KNOWLEDGE_DECISION_PREFIX = "FMVIS_KNOWLEDGE_DECISION "
IDENTITY_PREFIX = "FMVIS_IDENTITY "

PLAYER_TYPE_OFFSET = 0x6D92778
PLAYER_FROM_PERSON_OFFSET = 0x1C0
ACTUAL_PERSON_FROM_PLAYER_OFFSET = 0x1E8


def _csv_ints(name):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return frozenset()
    return frozenset(int(item, 0) for item in raw.split(","))


def _read_uint(inferior, address, size, signed=False):
    return int.from_bytes(
        bytes(inferior.read_memory(address, size)),
        "little",
        signed=signed,
    )


MODULE_BASE = int(os.environ["FMVIS_MODULE_BASE"], 0)
EXPECTED_PLAYER_TYPE = MODULE_BASE + PLAYER_TYPE_OFFSET


def _identity_at_known_address(inferior, address):
    candidates = (
        (address, "person"),
        (address + PLAYER_FROM_PERSON_OFFSET, "player"),
        (
            address
            + PLAYER_FROM_PERSON_OFFSET
            - ACTUAL_PERSON_FROM_PLAYER_OFFSET,
            "actual-person",
        ),
    )
    for person, kind in candidates:
        if person < 0x10000:
            continue
        try:
            if _read_uint(inferior, person, 8) != EXPECTED_PLAYER_TYPE:
                continue
            row_id = _read_uint(inferior, person + 8, 4, signed=True)
            player_id = _read_uint(inferior, person + 0xC, 4, signed=True)
        except Exception:
            continue
        if row_id >= 0 and player_id >= 0:
            return (player_id, row_id), kind
    return None


def _resolve_render_identity(inferior, render_reference):
    direct = _identity_at_known_address(inferior, render_reference)
    if direct is not None:
        identity, kind = direct
        return identity[0], f"direct-{kind}", None

    try:
        adjustment_table = _read_uint(inferior, render_reference + 8, 8)
        adjustment = _read_uint(
            inferior,
            adjustment_table + 4,
            4,
            signed=True,
        )
        person = render_reference + 8 + adjustment
    except Exception:
        return None, "unresolved", None
    match = _identity_at_known_address(inferior, person)
    if match is None or match[1] != "person":
        return None, "unresolved", None
    identity, _kind = match
    return identity[0], "interface-person", adjustment
class _VisibleResultBreakpoint(gdb.Breakpoint):
    def __init__(self):
        address = int(os.environ["FMVIS_BREAKPOINT"], 0)
        super().__init__(f"*{address:#x}", internal=True)
        self.allowed_attributes = _csv_ints("FMVIS_ATTRIBUTE_IDS")
        self.allowed_players = _csv_ints("FMVIS_PLAYER_IDS")
        self.diagnostic_hits = os.environ.get("FMVIS_DIAGNOSTIC_HITS") == "1"

    def stop(self):
        try:
            inferior = gdb.selected_inferior()
            attribute_id = int(gdb.parse_and_eval("$r14")) & 0xFF
            if self.diagnostic_hits:
                hit = {"attribute_id": attribute_id}
                gdb.write(HIT_PREFIX + json.dumps(hit, sort_keys=True) + "\n")
                gdb.flush()
            if attribute_id not in self.allowed_attributes:
                return False

            render_reference = int(gdb.parse_and_eval("$r15"))
            player_id, identity_status, identity_offset = _resolve_render_identity(
                inferior,
                render_reference,
            )
            identity_event = {
                "offset": identity_offset,
                "status": identity_status,
            }
            gdb.write(
                IDENTITY_PREFIX
                + json.dumps(identity_event, sort_keys=True)
                + "\n"
            )
            gdb.flush()
            if player_id is None:
                return False
            if self.allowed_players and player_id not in self.allowed_players:
                return False

            result_address = int(gdb.parse_and_eval("$rdx"))
            # Deliberately read exactly two visible bytes. A third byte in this
            # structure can retain concealed truth and must never be touched.
            visible = bytes(inferior.read_memory(result_address, 2))
            event = {
                "attribute_id": attribute_id,
                "lower": visible[0],
                "player_id": player_id,
                "upper": visible[1],
            }
            gdb.write(EVENT_PREFIX + json.dumps(event, sort_keys=True) + "\n")
            gdb.flush()
        except Exception as exc:
            error = {"message": f"{type(exc).__name__}: {exc}"}
            gdb.write(ERROR_PREFIX + json.dumps(error, sort_keys=True) + "\n")
            gdb.flush()
        return False


class _KnowledgeResultBreakpoint(gdb.Breakpoint):
    def __init__(self):
        address = int(os.environ["FMVIS_KNOWLEDGE_BREAKPOINT"], 0)
        super().__init__(f"*{address:#x}", internal=True)

    def stop(self):
        try:
            inferior = gdb.selected_inferior()
            context_address = int(gdb.parse_and_eval("$r14"))
            player_reference = int(gdb.parse_and_eval("$rbx"))
            record_address = int(gdb.parse_and_eval("$rax"))
            player_row_id = _read_uint(
                inferior, player_reference + 8, 4, signed=True
            )
            identity_match = _identity_at_known_address(
                inferior, player_reference
            )
            player_id = (
                identity_match[0][0] if identity_match is not None else None
            )
            context_owner_address = int.from_bytes(
                bytes(inferior.read_memory(context_address + 0x18, 8)),
                "little",
                signed=False,
            )
            vector_start = int.from_bytes(
                bytes(inferior.read_memory(context_address, 8)),
                "little",
                signed=False,
            )
            vector_end = int.from_bytes(
                bytes(inferior.read_memory(context_address + 8, 8)),
                "little",
                signed=False,
            )
            vector_size = vector_end - vector_start
            local_entry_count = (
                vector_size // 8
                if vector_start and vector_size >= 0 and vector_size % 8 == 0
                else None
            )
            knowledge_level = (
                int(bytes(inferior.read_memory(record_address + 8, 1))[0])
                if record_address
                else None
            )
            event = {
                "context_address": context_address,
                "context_owner_address": context_owner_address,
                "knowledge_level": knowledge_level,
                "local_entry_count": local_entry_count,
                "player_id": player_id,
                "player_row_id": player_row_id,
                "record_address": record_address,
            }
            gdb.write(KNOWLEDGE_PREFIX + json.dumps(event, sort_keys=True) + "\n")
            gdb.flush()
        except Exception as exc:
            error = {"message": f"{type(exc).__name__}: {exc}"}
            gdb.write(ERROR_PREFIX + json.dumps(error, sort_keys=True) + "\n")
            gdb.flush()
        return False


PENDING_KNOWLEDGE_DECISIONS = {}
CURRENT_KNOWLEDGE_CONTEXT = {}


def _thread_key():
    thread = gdb.selected_thread()
    return tuple(thread.ptid) if thread is not None else (0, 0, 0)


class _KnowledgeContextEntryBreakpoint(gdb.Breakpoint):
    def __init__(self):
        address = int(
            os.environ["FMVIS_KNOWLEDGE_CONTEXT_ENTRY_BREAKPOINT"], 0
        )
        super().__init__(f"*{address:#x}", internal=True)

    def stop(self):
        try:
            CURRENT_KNOWLEDGE_CONTEXT[_thread_key()] = {
                "attribute_id": int(gdb.parse_and_eval("$r8")) & 0xFF,
            }
        except Exception as exc:
            error = {"message": f"{type(exc).__name__}: {exc}"}
            gdb.write(ERROR_PREFIX + json.dumps(error, sort_keys=True) + "\n")
            gdb.flush()
        return False


class _KnowledgeDecisionEntryBreakpoint(gdb.Breakpoint):
    def __init__(self):
        address = int(
            os.environ["FMVIS_KNOWLEDGE_DECISION_ENTRY_BREAKPOINT"], 0
        )
        super().__init__(f"*{address:#x}", internal=True)

    def stop(self):
        try:
            inferior = gdb.selected_inferior()
            context = CURRENT_KNOWLEDGE_CONTEXT.get(_thread_key())
            if context is None:
                raise RuntimeError("knowledge decision has no attribute context")
            player_reference = int(gdb.parse_and_eval("$rbx"))
            player_id, _status, _offset = _resolve_render_identity(
                inferior, player_reference
            )
            PENDING_KNOWLEDGE_DECISIONS.setdefault(_thread_key(), []).append(
                {
                    "attribute_id": context["attribute_id"],
                    "player_id": player_id,
                }
            )
        except Exception as exc:
            error = {"message": f"{type(exc).__name__}: {exc}"}
            gdb.write(ERROR_PREFIX + json.dumps(error, sort_keys=True) + "\n")
            gdb.flush()
        return False


class _KnowledgeDecisionMergeBreakpoint(gdb.Breakpoint):
    def __init__(self):
        address = int(
            os.environ["FMVIS_KNOWLEDGE_DECISION_MERGE_BREAKPOINT"], 0
        )
        super().__init__(f"*{address:#x}", internal=True)

    def stop(self):
        try:
            pending = PENDING_KNOWLEDGE_DECISIONS.get(_thread_key(), [])
            if not pending:
                raise RuntimeError("knowledge decision merge has no entry")
            explicit_knowledge = int(gdb.parse_and_eval("$rbx")) & 0xFF
            baseline_knowledge = int(gdb.parse_and_eval("$rax")) & 0xFF
            pending[-1].update(
                {
                    "baseline_knowledge": baseline_knowledge,
                    "explicit_knowledge": explicit_knowledge,
                    "merged_knowledge": max(
                        explicit_knowledge, baseline_knowledge
                    ),
                }
            )
        except Exception as exc:
            error = {"message": f"{type(exc).__name__}: {exc}"}
            gdb.write(ERROR_PREFIX + json.dumps(error, sort_keys=True) + "\n")
            gdb.flush()
        return False


class _KnowledgeDecisionResultBreakpoint(gdb.Breakpoint):
    def __init__(self):
        address = int(
            os.environ["FMVIS_KNOWLEDGE_DECISION_RESULT_BREAKPOINT"], 0
        )
        super().__init__(f"*{address:#x}", internal=True)

    def stop(self):
        try:
            pending = PENDING_KNOWLEDGE_DECISIONS.get(_thread_key(), [])
            if not pending:
                raise RuntimeError("knowledge decision result has no entry")
            event = pending.pop()
            player_id = event.get("player_id")
            if player_id is None:
                return False
            required = {
                "baseline_knowledge",
                "explicit_knowledge",
                "merged_knowledge",
            }
            if not required.issubset(event):
                raise RuntimeError("knowledge decision result has no merge")
            effective_knowledge = int(gdb.parse_and_eval("$rdx")) & 0xFF
            range_threshold = int(gdb.parse_and_eval("$r12")) & 0xFF
            exact_threshold = int(gdb.parse_and_eval("$rbp")) & 0xFF
            classification = (
                "known"
                if effective_knowledge >= exact_threshold
                else "range"
                if effective_knowledge >= range_threshold
                else "unknown"
            )
            event = {
                **event,
                "classification": classification,
                "effective_knowledge": effective_knowledge,
                "exact_threshold": exact_threshold,
                "player_id": player_id,
                "range_threshold": range_threshold,
            }
            gdb.write(
                KNOWLEDGE_DECISION_PREFIX
                + json.dumps(event, sort_keys=True)
                + "\n"
            )
            gdb.flush()
        except Exception as exc:
            error = {"message": f"{type(exc).__name__}: {exc}"}
            gdb.write(ERROR_PREFIX + json.dumps(error, sort_keys=True) + "\n")
            gdb.flush()
        return False


_VisibleResultBreakpoint()
if os.environ.get("FMVIS_TRACE_KNOWLEDGE_CACHE") == "1":
    _KnowledgeResultBreakpoint()
if os.environ.get("FMVIS_TRACE_KNOWLEDGE_DECISION") == "1":
    _KnowledgeContextEntryBreakpoint()
    _KnowledgeDecisionEntryBreakpoint()
    _KnowledgeDecisionMergeBreakpoint()
    _KnowledgeDecisionResultBreakpoint()
gdb.write("FMVIS_READY\n")
gdb.flush()
end
continue

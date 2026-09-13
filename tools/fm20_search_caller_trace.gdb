python
"""Research-only: count callers of known manager-knowledge functions.

Each breakpoint reads only the return address at function entry ([rsp]) and
never writes registers or memory. Output is throttled: one line the first
time a (function, caller) pair is seen, then one line every 500 hits.
"""

import json
import os
import gdb


CALLER_PREFIX = "FMVIS_CALLER "
PLAYER_PREFIX = "FMVIS_SEARCH_PLAYER "
PLAYER_OFFSET_PREFIX = "FMVIS_SEARCH_PLAYER_OFFSET "
ERROR_PREFIX = "FMVIS_ERROR "
MODULE_BASE = int(os.environ["FMVIS_MODULE_BASE"], 0)
MODULE_END = int(os.environ["FMVIS_MODULE_END"], 0)
PERSON_HEADERS = (
    (0x1C8, MODULE_BASE + 0x6D92778),  # db::ACTUAL_PLAYER
    (0x2A0, MODULE_BASE + 0x6DA94A0),  # db::ACTUAL_PLAYER_AND_NON_PLAYER
)
HIT_LIMIT = int(os.environ.get("FMVIS_HIT_LIMIT", "200000"))
TARGETS = json.loads(os.environ["FMVIS_TRACE_TARGETS"])
CAPTURE_CANDIDATES = os.environ.get("FMVIS_CAPTURE_CANDIDATES") == "1"
COUNTS = {}
# Distinct second-argument values per function. Some evaluators receive a
# reusable wrapper, so its address alone does not count candidate players.
RECORDS = {}
RECORD_PAYLOADS = {}
RECORD_CAP = 400000
RESOLVED_OFFSETS = set()
# These evaluators receive a reusable filterable wrapper in RDX; the
# candidate player interface is the pointer stored at wrapper + 8.
PAYLOAD_RULES = {
    "rule_person_position",
    "rule_person_transfer_listed",
    "rule_player_scouted",
    "rule_person_interested_loan",
}


def _player_id_from_interface(inferior, interface):
    for offset, expected_type in PERSON_HEADERS:
        person = interface + offset
        try:
            type_ptr = int.from_bytes(bytes(inferior.read_memory(person, 8)), "little")
            if type_ptr != expected_type:
                continue
            row_id = int.from_bytes(
                bytes(inferior.read_memory(person + 8, 4)), "little", signed=True
            )
            player_id = int.from_bytes(
                bytes(inferior.read_memory(person + 0xC, 4)), "little", signed=True
            )
            if row_id >= 0 and player_id >= 0:
                if offset not in RESOLVED_OFFSETS:
                    RESOLVED_OFFSETS.add(offset)
                    gdb.write(PLAYER_OFFSET_PREFIX + str(offset) + "\n")
                    gdb.flush()
                return player_id
        except Exception:
            continue
    return None


class _CallerBreakpoint(gdb.Breakpoint):
    def __init__(self, label, rva):
        super().__init__(f"*{MODULE_BASE + rva:#x}", internal=True)
        self.label = label
        self.hits = 0

    def stop(self):
        try:
            self.hits += 1
            if self.hits >= HIT_LIMIT:
                self.enabled = False
            rsp = int(gdb.parse_and_eval("$rsp"))
            ret = int.from_bytes(
                bytes(gdb.selected_inferior().read_memory(rsp, 8)), "little"
            )
            caller = ret - MODULE_BASE if MODULE_BASE <= ret < MODULE_END else -1
            second_arg = int(gdb.parse_and_eval("$rdx"))
            records = RECORDS.setdefault(self.label, set())
            new_second_arg = second_arg not in records
            if len(records) < RECORD_CAP:
                records.add(second_arg)
            if CAPTURE_CANDIDATES and self.label == "large_field_switch" and new_second_arg:
                player_id = _player_id_from_interface(
                    gdb.selected_inferior(), second_arg
                )
                gdb.write(
                    PLAYER_PREFIX
                    + json.dumps({"pointer": second_arg, "player_id": player_id})
                    + "\n"
                )
                gdb.flush()
            payload_count = None
            if self.label in PAYLOAD_RULES:
                payload = int.from_bytes(
                    bytes(gdb.selected_inferior().read_memory(second_arg + 8, 8)),
                    "little",
                )
                payloads = RECORD_PAYLOADS.setdefault(self.label, set())
                if len(payloads) < RECORD_CAP:
                    payloads.add(payload)
                payload_count = len(payloads)
            key = (self.label, caller)
            count = COUNTS.get(key, 0) + 1
            COUNTS[key] = count
            if count == 1 or count % 500 == 0:
                gdb.write(
                    CALLER_PREFIX
                    + json.dumps(
                        {
                            "function": self.label,
                            "caller_rva": caller,
                            "count": count,
                            "distinct_rdx": len(records),
                            "distinct_record_payloads": payload_count,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                gdb.flush()
        except Exception as exc:
            gdb.write(
                ERROR_PREFIX
                + json.dumps({"message": f"{type(exc).__name__}: {exc}"})
                + "\n"
            )
            gdb.flush()
        return False


for label, rva in TARGETS.items():
    _CallerBreakpoint(label, int(rva, 0))
gdb.write("FMVIS_READY\n")
gdb.flush()
end
continue

python
"""Research-only: passively record FM's own arguments to the visible-result
builder (RVA 0x15A4A90) for a genuine, screen-triggered call.

This exists because the cold-call harnesses fabricate the builder's 5th
argument (optional report object, hardcoded null) and 6th argument (a small
caller-owned context, hardcoded to {manager, 1}), and a systematic check
against real FM exports proved that fabrication sometimes produces a visible
range where FM's own UI shows nothing. This hook sets no breakpoint condition,
performs no register or memory writes, and never continues execution itself
beyond GDB's normal auto-continue (`return False`) -- it is exactly the same
shape of passive read used everywhere else in this harness, at the same
address the cold-call tools target, just capturing the incoming arguments
instead of the outgoing result.
"""

import json
import os
import gdb


ARGS_PREFIX = "FMVIS_BUILDER_ARGS "
ERROR_PREFIX = "FMVIS_ERROR "

MODULE_BASE = int(os.environ["FMVIS_MODULE_BASE"], 0)
BUILDER_ADDRESS = int(os.environ["FMVIS_VISIBLE_RESULT_BUILDER_BREAKPOINT"], 0)


def _read_uint(inferior, address, size):
    return int.from_bytes(
        bytes(inferior.read_memory(address, size)), "little", signed=False
    )


def _peek(inferior, address, size):
    if not (0x10000 <= address < (1 << 48)):
        return None
    try:
        return bytes(inferior.read_memory(address, size)).hex()
    except gdb.MemoryError:
        return None


class _BuilderArgumentsBreakpoint(gdb.Breakpoint):
    def __init__(self):
        super().__init__(f"*{BUILDER_ADDRESS:#x}", internal=True)

    def stop(self):
        try:
            inferior = gdb.selected_inferior()
            stack_pointer = int(gdb.parse_and_eval("$rsp"))
            report_object = _read_uint(inferior, stack_pointer + 0x28, 8)
            small_context = _read_uint(inferior, stack_pointer + 0x30, 8)
            event = {
                "attributeId": int(gdb.parse_and_eval("$r9")) & 0xFF,
                "reportObject": hex(report_object),
                "reportObjectBytes": _peek(inferior, report_object, 32),
                "smallContext": hex(small_context),
                "smallContextBytes": _peek(inferior, small_context, 16),
            }
            gdb.write(ARGS_PREFIX + json.dumps(event, sort_keys=True) + "\n")
            gdb.flush()
        except Exception as exc:
            error = {"message": f"{type(exc).__name__}: {exc}"}
            gdb.write(ERROR_PREFIX + json.dumps(error, sort_keys=True) + "\n")
            gdb.flush()
        return False


_BuilderArgumentsBreakpoint()
gdb.write("FMVIS_READY\n")
gdb.flush()
end
continue

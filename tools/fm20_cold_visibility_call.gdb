python
"""Research-only MS x64 call of FM's visible-result builder on FM's main thread.

The caller validates all object identities before starting GDB. This script
prints only the two public result bytes; the third byte is never read.
"""

import json
import os
import gdb


def reg(name):
    return int(gdb.parse_and_eval("$" + name))


def set_reg(name, value):
    gdb.execute(f"set ${name} = {value:#x}", to_string=True)


def put(address, value, size=8):
    gdb.selected_inferior().write_memory(
        address, int(value).to_bytes(size, "little")
    )


pid = int(os.environ["FM_COLD_PID"])
module_base = int(os.environ["FM_COLD_MODULE_BASE"], 0)
context = int(os.environ["FM_COLD_CONTEXT"], 0)
player = int(os.environ["FM_COLD_PLAYER_INTERFACE"], 0)
attribute = int(os.environ["FM_COLD_ATTRIBUTE_ID"], 0)
thread = next(
    item for item in gdb.selected_inferior().threads()
    if item.ptid[1] == pid
)
thread.switch()
saved = {
    name: reg(name)
    for name in (
        "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "rip",
        "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15", "eflags",
    )
}

# A Windows x64 callee enters with rsp % 16 == 8. The caller owns 32 bytes
# of shadow space; arguments five and six follow it. Keep scratch objects
# above those slots and below the original stack pointer.
call_rsp = ((saved["rsp"] - 0x400) & ~0xF) | 8
result = call_rsp + 0xA0
small_context = call_rsp + 0x80
# The preceding function ends in verified INT3 padding. Returning to one of
# those bytes gives us a unique stop without patching the interrupted RIP.
return_trap = module_base + 0x15A4A84
put(call_rsp, return_trap)
put(call_rsp + 0x28, 0)  # optional report object
put(call_rsp + 0x30, small_context)
put(small_context, 0)
put(small_context + 8, 1)
put(result, 0xFFFFFFFFFFFFFFFF)

set_reg("rcx", context)
set_reg("rdx", result)
set_reg("r8", player)
set_reg("r9", attribute)
set_reg("rsp", call_rsp)
set_reg("rip", module_base + 0x15A4A90)

try:
    entry_rip = reg("rip")
    entry_byte = bytes(gdb.selected_inferior().read_memory(entry_rip, 1)).hex()
    step_description = gdb.execute("stepi", to_string=True)
    stepped_rip = reg("rip")
    if stepped_rip != module_base + 0x15A4A95:
        gdb.write(
            "FM_COLD_STOP "
            + json.dumps({
                "phase": "entry-step",
                "entry_rip": hex(entry_rip),
                "entry_byte": entry_byte,
                "stepped_rip": hex(stepped_rip),
                "description": step_description[-600:],
                "program": gdb.execute("info program", to_string=True)[-600:],
                "breakpoints": gdb.execute("info breakpoints", to_string=True)[-400:],
            })
            + "\n"
        )
        raise RuntimeError("FM did not execute the builder entry instruction")
    stop_description = gdb.execute("continue", to_string=True)
    if gdb.selected_thread().num != thread.num or reg("rip") not in (
        return_trap, return_trap + 1
    ):
        gdb.write(
            "FM_COLD_STOP "
            + json.dumps({
                "thread": gdb.selected_thread().num,
                "expected_thread": thread.num,
                "rip": hex(reg("rip")),
                "expected_return_trap": hex(return_trap),
                "description": stop_description[-600:],
            })
            + "\n"
        )
        raise RuntimeError("FM did not return to the selected main thread")
    public = bytes(gdb.selected_inferior().read_memory(result, 2))
    gdb.write(
        "FM_COLD_RESULT "
        + json.dumps({"lower": public[0], "upper": public[1]})
        + "\n"
    )
finally:
    if thread.is_valid():
        thread.switch()
        for name, value in saved.items():
            set_reg(name, value)
    gdb.execute("detach", to_string=True)
end
quit

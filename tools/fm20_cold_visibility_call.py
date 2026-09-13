#!/usr/bin/env python3
"""Research-only direct FM20 visibility query; never use as a public source.

The player ID must already be known to be discoverable. This tool does not
establish discoverability and must not be wired into the application bridge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fm_analytics.bridge.visibility_result import decode_visible_bound_bytes
from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    parse_module_mapping,
    read_human_manager_contexts,
    read_i32,
    read_pointer_collection,
    read_u64,
    validate_executable,
)
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_visibility_trace import DISPLAY_ATTRIBUTE_IDS


EXPECTED_SHA256 = "fd2c877ef28927dc63b0009ec6a2d46bdba158f456a29ecb342062cb9d82b102"
CONTEXT_ROOT_RVA = 0x746A440
BUILDER_SCRIPT = Path(__file__).with_suffix(".gdb")
RESULT_PREFIX = "FM_COLD_RESULT "


def resolve_cold_call_addresses(
    memory_fd: int,
    module_base: int,
    player_id: int,
    active_manager_id: str,
) -> tuple[int, int, int]:
    """Resolve (context, manager_interface, player_interface) addresses.

    Pure given an already-open, already-validated process memory fd and the
    already-verified active manager's ID: every guard fails closed rather than
    returning a best-effort address. Kept free of the human-manager collection
    scan so it can be exercised with synthetic memory in tests.
    """

    root = read_u64(memory_fd, module_base + CONTEXT_ROOT_RVA)
    if not root:
        raise ProbeError("manager-knowledge context root is missing")
    start = read_u64(memory_fd, root + 0x18)
    end = read_u64(memory_fd, root + 0x20)
    if not start or end - start != 8:
        raise ProbeError("expected exactly one manager-knowledge context")
    context = read_u64(memory_fd, start)
    if not context:
        raise ProbeError("manager-knowledge context is null")
    manager_person = read_u64(memory_fd, context + 0x18)
    if read_u64(memory_fd, manager_person) != module_base + FM20_4_4_STEAM.human_manager_type_offset:
        raise ProbeError("knowledge-context owner is not a human manager")
    if active_manager_id != str(read_i32(memory_fd, manager_person + 0xC)):
        raise ProbeError("knowledge-context owner is not the active manager")
    manager_interface = manager_person - 0x480
    manager_table = read_u64(memory_fd, manager_interface + 8)
    if manager_interface + 8 + read_i32(memory_fd, manager_table + 4) != manager_person:
        raise ProbeError("manager interface adjustment does not resolve to owner")

    people = read_pointer_collection(
        memory_fd,
        module_base,
        FM20_4_4_STEAM.main_address_offset,
        FM20_4_4_STEAM.person_collection_offset,
        FM20_4_4_STEAM.collection_indirection_offset,
    )
    matches = [
        address for address in people
        if address
        and read_u64(memory_fd, address) == module_base + FM20_4_4_STEAM.player_type_offset
        and read_i32(memory_fd, address + 0xC) == player_id
    ]
    if len(matches) != 1:
        raise ProbeError("player ID did not resolve uniquely to a loaded player")
    player_person = matches[0]
    player_interface = player_person - 0x1C8
    player_table = read_u64(memory_fd, player_interface + 8)
    if player_interface + 8 + read_i32(memory_fd, player_table + 4) != player_person:
        raise ProbeError("player interface adjustment does not resolve to player")
    return context, manager_interface, player_interface


def preflight(pid: int, player_id: int, attribute: str) -> dict[str, str]:
    process = Path("/proc") / str(pid)
    with (process / "maps").open(encoding="utf-8") as mappings:
        module_base, executable = parse_module_mapping(mappings)
    validate_executable(executable)
    with Path(executable).open("rb") as image:
        digest = hashlib.file_digest(image, "sha256").hexdigest()
    if digest != EXPECTED_SHA256:
        raise ProbeError("FM executable hash differs from the traced build")

    fd = os.open(process / "mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        managers = read_human_manager_contexts(fd, module_base)
        active = [item.manager for item in managers if item.manager.active]
        if len(active) != 1:
            raise ProbeError("expected exactly one active human manager")
        context, manager_interface, player_interface = resolve_cold_call_addresses(
            fd, module_base, player_id, active[0].id
        )
    finally:
        os.close(fd)

    return {
        "FM_COLD_PID": str(pid),
        "FM_COLD_MODULE_BASE": hex(module_base),
        "FM_COLD_CONTEXT": hex(context),
        "FM_COLD_PLAYER_INTERFACE": hex(player_interface),
        "FM_COLD_MANAGER_INTERFACE": hex(manager_interface),
        "FM_COLD_ATTRIBUTE_ID": hex(DISPLAY_ATTRIBUTE_IDS[attribute]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--player-id", type=int, required=True)
    parser.add_argument("--attribute", choices=sorted(DISPLAY_ATTRIBUTE_IDS), required=True)
    parser.add_argument("--acknowledge-native-call", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run preflight only; never attach or call into FM",
    )
    args = parser.parse_args()
    if not args.dry_run and not args.acknowledge_native_call:
        parser.error("--acknowledge-native-call is required unless --dry-run is set")
    try:
        preflight_environment = preflight(
            choose_pid(args.pid), args.player_id, args.attribute
        )
        if args.dry_run:
            print(json.dumps(preflight_environment, sort_keys=True))
            return 0
        environment = os.environ | preflight_environment
        process = subprocess.run(
            [
                "gdb", "-q", "-nx", "-batch", "-ex", "set pagination off",
                "-ex", "set confirm off", "-ex", "set print thread-events off",
                "-ex", "handle SIGUSR1 nostop noprint pass",
                "-p", environment["FM_COLD_PID"],
                "-ex", f"source {BUILDER_SCRIPT}",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        results = [
            json.loads(line.removeprefix(RESULT_PREFIX))
            for line in process.stdout.splitlines()
            if line.startswith(RESULT_PREFIX)
        ]
        if process.returncode or len(results) != 1:
            stop = next(
                (line for line in process.stdout.splitlines() if line.startswith("FM_COLD_STOP ")),
                "",
            )
            raise ProbeError(
                f"native call did not complete (gdb exit {process.returncode}); "
                f"stop: {stop}; gdb diagnostic: {process.stderr[-900:].strip()}"
            )
        bounds = results[0]
        if set(bounds) != {"lower", "upper"}:
            raise ProbeError("native call returned an unexpected public-byte contract")
        observation = decode_visible_bound_bytes(bounds["lower"], bounds["upper"])
    except (OSError, ProbeError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "playerId": str(args.player_id),
        "attribute": args.attribute,
        "visibility": observation.visibility.value,
        "value": observation.value,
        "minimum": observation.minimum,
        "maximum": observation.maximum,
        "researchOnly": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

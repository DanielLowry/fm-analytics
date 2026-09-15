#!/usr/bin/env python3
"""Thin recipe controller for bounded, evidence-backed FM20 research."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from tools.fm20_field_workbench import verified_executable_digest
from tools.fm20_linux_probe import ProbeError
from tools.fm20_linux_probe_runtime import choose_pid, probe
from tools.validate_research_catalog import CatalogueError, load_json, validate


ROOT = Path(__file__).resolve().parents[1]
RECIPE_DIR = ROOT / "research" / "recipes"
REGISTRY_PATH = ROOT / "research" / "registry.json"
CORPUS_PATH = ROOT / "research" / "corpus.json"
DEFAULT_REPORT_DIR = ROOT / "data" / "research" / "sessions"
SCHEMA_VERSION = 1
MAX_CAPTURED_OUTPUT = 16_384


class ControllerError(RuntimeError):
    """The controller could not safely plan or complete an experiment."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_recipe(recipe_id: str) -> dict[str, Any]:
    if not recipe_id or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in recipe_id):
        raise ControllerError("recipe ID may contain only lowercase letters, digits, and hyphens")
    path = RECIPE_DIR / f"{recipe_id}.json"
    if not path.is_file():
        available = ", ".join(item.stem for item in sorted(RECIPE_DIR.glob("*.json")))
        raise ControllerError(f"unknown recipe {recipe_id!r}; available: {available or 'none'}")
    recipe = load_json(path)
    if recipe.get("schema_version") != 1 or recipe.get("id") != recipe_id:
        raise ControllerError(f"{path}: invalid recipe schema or ID")
    adapter = recipe.get("adapter")
    if adapter not in {"fm20-field-workbench", "fm20-frida-trace"}:
        raise ControllerError(f"recipe uses unsupported adapter {adapter!r}")
    if recipe.get("safety") != "passive-live":
        raise ControllerError("controller recipes must currently be passive-live")
    if recipe.get("operator_interaction") not in {"none", "one-short-batched-ui-tour"}:
        raise ControllerError("recipe has an unsupported operator-interaction contract")
    timeout = recipe.get("timeout_seconds")
    if not isinstance(timeout, int) or not 5 <= timeout <= 300:
        raise ControllerError("recipe timeout_seconds must be an integer from 5 to 300")
    if adapter == "fm20-field-workbench":
        if recipe.get("adapter_mode") != "run":
            raise ControllerError("field-workbench recipes may use only non-interactive run mode")
        fields = recipe.get("fields")
        if not isinstance(fields, list) or not fields or any(field not in {"footedness", "position_proficiency"} for field in fields):
            raise ControllerError("recipe contains no supported field")
    else:
        targets = recipe.get("targets")
        if not isinstance(targets, list) or any(not isinstance(target, str) for target in targets):
            raise ControllerError("Frida recipe targets must be a list of registry function IDs")
        duration = recipe.get("duration_seconds")
        event_limit = recipe.get("max_events")
        if not isinstance(duration, (int, float)) or not 0.25 <= duration <= 300:
            raise ControllerError("Frida duration_seconds must be from 0.25 to 300")
        if not isinstance(event_limit, int) or not 1 <= event_limit <= 10_000:
            raise ControllerError("Frida max_events must be from 1 to 10000")
    return recipe


def _registry_ids(registry: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    for section in (
        "types",
        "instrumentation_backends",
        "object_resolvers",
        "functions",
        "properties",
        "visibility_rules",
        "discoverability_rules",
        "experiments",
    ):
        identifiers.update(item["id"] for item in registry.get(section, []))
    return identifiers


def plan_recipe(recipe_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    missing_artifacts = validate()
    recipe = load_recipe(recipe_id)
    registry = load_json(REGISTRY_PATH)
    corpus = load_json(CORPUS_PATH)

    build_ids = {item["id"] for item in registry["builds"]}
    if recipe.get("build") not in build_ids:
        raise ControllerError(f"recipe references unknown build {recipe.get('build')!r}")
    unknown_facts = set(recipe.get("required_registry_facts", [])) - _registry_ids(registry)
    if unknown_facts:
        raise ControllerError(f"recipe references unknown registry facts: {', '.join(sorted(unknown_facts))}")
    corpus_by_id = {item["id"]: item for item in corpus["entries"]}
    unknown_states = set(recipe.get("reusable_corpus_states", [])) - set(corpus_by_id)
    if unknown_states:
        raise ControllerError(f"recipe references unknown corpus states: {', '.join(sorted(unknown_states))}")

    missing_paths = set(missing_artifacts)
    state_coverage = []
    for state_id in recipe.get("reusable_corpus_states", []):
        entry = corpus_by_id[state_id]
        paths = [capture["path"] for capture in entry.get("captures", [])]
        state_coverage.append({
            "id": state_id,
            "catalogued": True,
            "artifacts_present": all(path not in missing_paths for path in paths),
            "captures": paths,
            "limitations": entry.get("limitations", []),
        })
    plan = {
        "catalogue_valid": True,
        "build": recipe["build"],
        "safety": recipe["safety"],
        "operator_interaction": recipe["operator_interaction"],
        "required_registry_facts": recipe.get("required_registry_facts", []),
        "corpus_state_coverage": state_coverage,
        "requires_live_process": recipe["requires_live_process"],
        "timeout_seconds": recipe["timeout_seconds"],
        "operator_actions": recipe.get("operator_actions", {}),
    }
    return recipe, plan


def _snapshot_summary(snapshot: Any) -> dict[str, Any]:
    if is_dataclass(snapshot):
        values = asdict(snapshot)
    elif isinstance(snapshot, dict):
        values = snapshot
    else:
        values = vars(snapshot)
    managers = values.get("human_managers", ())

    def mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if is_dataclass(value):
            return asdict(value)
        return vars(value)

    manager_values = [mapping(manager) for manager in managers]
    active = [manager for manager in manager_values if manager.get("active")]
    if len(active) != 1:
        raise ControllerError("preflight expected exactly one active human manager")
    active_manager = active[0]
    club = mapping(active_manager["club"]) if active_manager.get("club") else None
    squad = values.get("first_team_squad", ())
    squad_ids = sorted(str(mapping(player)["id"]) for player in squad)
    return {
        "pid": values["pid"],
        "executable": values["executable"],
        "module_base": values["module_base"],
        "profile": values["profile"],
        "game_date": values["game_date"],
        "manager_id": str(active_manager["id"]),
        "club_id": str(club["id"]) if club else None,
        "squad_count": len(squad_ids),
        "squad_id_hash": hashlib.sha256(",".join(squad_ids).encode("ascii")).hexdigest(),
    }


def _adapter_command(
    recipe: dict[str, Any],
    pid: int,
    executable: Path,
    module_base: str,
    report: Path,
) -> list[str]:
    if recipe["adapter"] == "fm20-field-workbench":
        command = [
            sys.executable,
            str(ROOT / "tools" / "fm20_field_workbench.py"),
            recipe["adapter_mode"],
            "--pid", str(pid),
            "--executable", str(executable),
            "--require-live",
            "--report", str(report),
        ]
        for field in recipe["fields"]:
            command.extend(("--field", field))
        return command

    registry = load_json(REGISTRY_PATH)
    functions = {item["id"]: item for item in registry["functions"]}
    command = [
        sys.executable,
        str(ROOT / "tools" / "fm20_frida_trace.py"),
        "--pid", str(pid),
        "--module-base", module_base,
        "--duration", str(recipe["duration_seconds"]),
        "--max-events", str(recipe["max_events"]),
        "--report", str(report),
    ]
    for target_id in recipe["targets"]:
        function = functions.get(target_id)
        if function is None or "rva" not in function:
            raise ControllerError(f"Frida target {target_id!r} has no registered function RVA")
        command.extend(("--target", f"{target_id}={function['rva']}"))
    if recipe.get("capture_backtraces"):
        command.append("--backtraces")
    return command


def _adapter_passed(
    recipe: dict[str, Any], completed: subprocess.CompletedProcess[str], adapter_report: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    decision = recipe["decision"]
    summary: dict[str, Any] = {
        "adapter_status": adapter_report.get("status"),
        "exit_code": completed.returncode,
    }
    passed = (
        completed.returncode in decision["adapter_exit_codes"]
        and adapter_report.get("status") in decision["adapter_statuses"]
    )
    if recipe["adapter"] == "fm20-field-workbench":
        summary["live_status"] = adapter_report.get("liveStatus")
        passed = passed and adapter_report.get("liveStatus") == decision["require_live_status"]
        return passed, summary

    capture_result = adapter_report.get("capture", {})
    summary.update({
        "attached": capture_result.get("attached"),
        "agent_ready": capture_result.get("agentReady"),
        "detached": capture_result.get("detached"),
        "process_alive": adapter_report.get("processAliveAfterDetach"),
        "entry_events": capture_result.get("entryEventCount", 0),
    })
    passed = passed and all((
        not decision.get("require_attached") or summary["attached"] is True,
        not decision.get("require_agent_ready") or summary["agent_ready"] is True,
        not decision.get("require_detached") or summary["detached"] is True,
        not decision.get("require_process_alive") or summary["process_alive"] is True,
        summary["entry_events"] >= decision.get("minimum_entry_events", 0),
    ))
    return passed, summary


def _bounded(value: str) -> str:
    if len(value) <= MAX_CAPTURED_OUTPUT:
        return value
    return value[:MAX_CAPTURED_OUTPUT] + "\n...[controller output limit reached]"


def _report_name(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def run_recipe(
    recipe_id: str,
    *,
    requested_pid: int | None = None,
    report_path: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[int, Path, dict[str, Any]]:
    started = utc_now()
    stamp = started.strftime("%Y%m%dT%H%M%S%fZ")
    target = report_path or DEFAULT_REPORT_DIR / f"{recipe_id}-{stamp}.json"
    adapter_target = target.with_name(f"{target.stem}.adapter.json")
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "researchOnly": True,
        "controller": "fm20_research",
        "recipe": recipe_id,
        "startedAt": started.isoformat(),
        "status": "started",
        "lifecycle": {
            "processDiscovery": "pending",
            "buildValidation": "pending",
            "attachment": "adapter-owned bounded read-only /proc access",
            "resourceRelease": "pending",
        },
    }
    status = 1
    try:
        if target.exists() or adapter_target.exists():
            raise ControllerError("controller or adapter report path already exists")
        recipe, plan = plan_recipe(recipe_id)
        report["plan"] = plan
        report["lifecycle"]["attachment"] = (
            "Frida injected agent; adapter owns unload and detach"
            if recipe["adapter"] == "fm20-frida-trace"
            else "adapter-owned bounded read-only /proc access"
        )
        pid = choose_pid(requested_pid)
        report["lifecycle"]["processDiscovery"] = "complete"
        snapshot = probe(pid)
        process = _snapshot_summary(snapshot)
        executable = Path(process["executable"])
        process["executable_sha256"] = verified_executable_digest(executable)
        report["process"] = process
        report["lifecycle"]["buildValidation"] = "complete"

        command = _adapter_command(recipe, pid, executable, process["module_base"], adapter_target)
        guided = recipe["operator_interaction"] != "none"
        if guided:
            actions = recipe.get("operator_actions", {})
            print(f"PREPARE: {actions.get('starting_state', 'use the declared recipe start state')}", flush=True)
            print(f"WHEN ARMED: {actions.get('after_armed', 'perform the declared bounded action batch')}", flush=True)
        completed = runner(
            command,
            check=False,
            capture_output=not guided,
            text=True,
            timeout=recipe["timeout_seconds"],
            cwd=ROOT,
        )
        report["lifecycle"]["resourceRelease"] = "confirmed-by-adapter-exit"
        execution: dict[str, Any] = {
            "adapter": recipe["adapter"],
            "exitCode": completed.returncode,
            "stdout": _bounded(completed.stdout or "") if not guided else "streamed to operator",
            "stderr": _bounded(completed.stderr or "") if not guided else "streamed to operator",
            "report": _report_name(adapter_target),
        }
        report["execution"] = execution
        if not adapter_target.is_file():
            raise ControllerError("adapter exited without producing its evidence report")
        adapter_report = load_json(adapter_target)
        execution["reportSha256"] = sha256(adapter_target)
        execution["adapterStatus"] = adapter_report.get("status")
        if adapter_report.get("researchOnly") is not True:
            raise ControllerError("adapter report is not marked research-only")
        if recipe["adapter"] == "fm20-frida-trace":
            capture = adapter_report.get("capture", {})
            report["lifecycle"]["resourceRelease"] = (
                "confirmed-by-adapter"
                if capture.get("detached") and capture.get("scriptUnloaded")
                else "not-confirmed-after-injection-failure"
            )
        try:
            postflight = _snapshot_summary(probe(pid))
        except ProbeError as error:
            report["postflight"] = {"available": False, "error": str(error)}
            if adapter_report.get("processAliveAfterDetach") is False:
                raise ControllerError(
                    "FM exited during the experiment; instrumentation is unsafe to retry"
                ) from error
            raise
        report["postflight"] = postflight
        invariant_keys = ("pid", "module_base", "profile", "game_date", "manager_id", "club_id", "squad_id_hash")
        report["invariants"] = {
            key: process[key] == postflight[key] for key in invariant_keys
        }
        if not all(report["invariants"].values()):
            raise ControllerError("FM process identity or managed game state changed during experiment")
        passed, decision_summary = _adapter_passed(recipe, completed, adapter_report)
        report["decision"] = {"passed": passed, **decision_summary}
        if not passed:
            raise ControllerError("adapter evidence did not satisfy the recipe decision rule")
        report["status"] = "complete"
        status = 0
    except (CatalogueError, ControllerError, ProbeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        if report["lifecycle"]["resourceRelease"] == "pending":
            report["lifecycle"]["resourceRelease"] = (
                "not-opened" if report["lifecycle"]["processDiscovery"] == "pending"
                else "controller-ended; adapter process absent or terminated"
            )
    report["endedAt"] = utc_now().isoformat()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    return status, target, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run",))
    parser.add_argument("recipe")
    parser.add_argument("--pid", type=int, help="FM20 host PID; auto-detected by default")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="validate and print the plan without touching FM")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run:
        try:
            recipe, plan = plan_recipe(args.recipe)
        except (CatalogueError, ControllerError, OSError, ValueError, json.JSONDecodeError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        result = {"status": "planned", "recipe": recipe["id"], "plan": plan}
        print(json.dumps(result, indent=2) if args.json else f"PLAN {recipe['id']} catalogue=valid interaction=none")
        return 0
    status, target, report = run_recipe(args.recipe, requested_pid=args.pid, report_path=args.report)
    if args.json:
        print(json.dumps({"status": report["status"], "report": str(target)}, indent=2))
    else:
        print(f"RESULT {target} status={report['status']}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())

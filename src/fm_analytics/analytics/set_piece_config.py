"""Strict loading of manager-visible set-piece weights, separate from mechanics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from fm_analytics.analytics.role_scoring import RoleAttribute
from fm_analytics.domain.attributes import VISIBLE_ATTRIBUTES
from fm_analytics.analytics.set_piece_defence import (
    DEFENSIVE_FREE_KICK_JOBS, DEFENSIVE_JOBS, DEFENSIVE_RESPONSIBILITIES,
    FLEXIBLE_DEFENSIVE_FREE_KICKS, DefensiveApproach, DefensiveTemplate,
    validate_defensive_counts,
)


DATA_DIR = Path(__file__).with_name("data") / "set_pieces"
FREE_KICK_VARIANTS = (
    "direct_free_kick", "direct_small_chance", "indirect_wide", "indirect_deep",
)
# These are the jobs/task identities the Python routine builders consume.
# The files own their weights, not the legal FM instructions or player counts.
_CORNER_ATTACK_JOBS = frozenset(
    "corner_" + suffix for suffix in (
        "taker", "attack_near", "lurk_near", "attack_far", "lurk_far",
        "mark_keeper", "come_short", "go_left", "go_right", "attack_edge",
        "lurk_outside", "stay", "cover", "wide_cover",
    )
)
_CORNER_DEFENCE_JOBS = frozenset(
    "def_corner_" + suffix for suffix in (
        "keeper", "post_near", "post_far", "zonal_near", "zonal_centre",
        "zonal_far", "go_back", "man_mark", "mark_tall", "edge", "forward",
    )
)
_FREE_KICK_ATTACK_JOBS = frozenset((
    "taker", "near", "far", "edge_left", "edge_right", "partner",
    "go_left", "go_centre", "go_right", "stay", "cover", "wide_cover",
))
_FREE_KICK_DEFENCE_JOBS = DEFENSIVE_JOBS | {"keeper"}
_TASK_FILES = {
    "corners": "attacking_corners",
    "attacking_aerial_target": "attacking_corners",
    "defensive_aerial_target": "defending_corners",
    "direct_free_kicks": "attacking_free_kicks",
    "indirect_free_kicks": "attacking_free_kicks",
    "penalties": "penalties",
    "long_throws": "long_throws",
}
_DEDICATED_TASKS = {
    "direct_free_kicks": "freeKickTaking", "indirect_free_kicks": "freeKickTaking",
    "penalties": "penaltyTaking",
}
_ATTRIBUTES = VISIBLE_ATTRIBUTES | {"freeKickTaking", "penaltyTaking", "longThrows"}


@dataclass(frozen=True)
class JobWeights:
    attributes: tuple[RoleAttribute, ...]
    importance: float


@dataclass(frozen=True)
class TakerWeights:
    attributes: tuple[RoleAttribute, ...]
    dedicated_attributes: tuple[RoleAttribute, ...] = ()


@dataclass(frozen=True)
class SetPieceWeights:
    version: str
    delivery_foot_bonus: float
    roles: Mapping[str, Mapping[str, JobWeights]]
    variants: Mapping[str, Mapping[str, Mapping[str, JobWeights]]]
    tasks: Mapping[str, TakerWeights]
    defensive_templates: Mapping[str, tuple[DefensiveTemplate, ...]]
    defensive_approaches: Mapping[str, DefensiveApproach]
    defensive_budgets: Mapping[str, Mapping[str, float]]

    def routine(self, family: str, variant: str | None = None) -> Mapping[str, JobWeights]:
        return self.roles[family] if variant is None else self.variants[family][variant]


def _object(value: object, context: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{context}: expected an object")
    return value


def _keys(value: dict, expected: set | frozenset, context: str) -> None:
    missing, extra = expected - value.keys(), value.keys() - expected
    if missing or extra:
        raise ValueError(f"{context}: missing keys {sorted(missing)}; unexpected keys {sorted(extra)}")


def _number(value: object, context: str, *, allow_zero: bool = False) -> float:
    try:
        number = float(value) if not isinstance(value, bool) and isinstance(value, (int, float)) else float("nan")
    except OverflowError:
        number = float("inf")
    if (
        not isfinite(number) or (number < 0 if allow_zero else number <= 0)
    ):
        kind = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{context}: expected a finite {kind} number")
    return number


def _read(path: Path) -> dict:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path.name}: duplicate key {key!r}")
            result[key] = value
        return result

    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream, object_pairs_hook=unique_object)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path.name}: {error}") from error
    return _object(value, path.name)


def _defensive_choices(document: dict, context: str):
    """Only reviewed, balanced structures enter the candidate catalogue."""
    raw_templates = _object(document["templates"], context + ".templates")
    _keys(raw_templates, FLEXIBLE_DEFENSIVE_FREE_KICKS, context + ".templates")
    templates = {}
    for kind, raw in raw_templates.items():
        where = context + ".templates." + kind
        if not isinstance(raw, list) or not raw:
            raise ValueError(f"{where}: expected a non-empty template array")
        entries, keys, shapes = [], set(), set()
        for index, value in enumerate(raw):
            label = f"{where}[{index}]"
            entry = _object(value, label)
            _keys(entry, {"key", "name", "description", "jobs"}, label)
            for field in ("key", "name", "description"):
                if not isinstance(entry[field], str) or not entry[field].strip():
                    raise ValueError(f"{label}.{field}: expected a non-empty string")
            jobs = _object(entry["jobs"], label + ".jobs")
            _keys(jobs, frozenset(DEFENSIVE_FREE_KICK_JOBS[kind]), label + ".jobs")
            if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in jobs.values()):
                raise ValueError(f"{label}: job counts must be non-negative integers")
            if sum(jobs.values()) != 10:
                raise ValueError(f"{label}: a template must assign all ten outfield players")
            try:
                validate_defensive_counts(kind, jobs)
            except ValueError as error:
                raise ValueError(f"{label}: {error}") from error
            shape = tuple(jobs[key] for key in sorted(jobs))
            if entry["key"] in keys or shape in shapes:
                raise ValueError(f"{label}: duplicate template key or job structure")
            keys.add(entry["key"])
            shapes.add(shape)
            entries.append(DefensiveTemplate(entry["key"], entry["name"], entry["description"], MappingProxyType(jobs), kind))
        templates[kind] = tuple(entries)

    raw_approaches = _object(document["approaches"], context + ".approaches")
    _keys(raw_approaches, {"secure", "balanced", "aggressive"}, context + ".approaches")
    approaches = {}
    for key, value in raw_approaches.items():
        where = context + ".approaches." + key
        entry = _object(value, where)
        _keys(entry, {"minimumBoxDefenders", "minimumSmallChanceBoxDefenders", "minimumOutlets", "maximumOutlets"}, where)
        if any(isinstance(n, bool) or not isinstance(n, int) for n in entry.values()):
            raise ValueError(f"{where}: coverage requirements must be integers")
        approach = DefensiveApproach(entry["minimumBoxDefenders"], entry["minimumOutlets"], entry["maximumOutlets"], entry["minimumSmallChanceBoxDefenders"])
        if (
            not 6 <= approach.minimum_box_defenders <= 8
            or not 4 <= approach.minimum_small_chance_box_defenders <= 6
            or not 1 <= approach.minimum_outlets <= approach.maximum_outlets <= 2
            or key == "secure" and (approach.minimum_box_defenders < 7 or approach.minimum_small_chance_box_defenders < 5 or approach.maximum_outlets != 1)
            or key == "aggressive" and approach.minimum_outlets != 2
        ):
            raise ValueError(f"{where}: approach must retain defensive coverage and its requested outlet commitment")
        for kind, choices in templates.items():
            if not any(approach.accepts(choice) for choice in choices):
                raise ValueError(f"{where}: no eligible {kind} template")
        approaches[key] = approach
    budgets = {}
    raw_budgets = _object(document["budgets"], context + ".budgets")
    _keys(raw_budgets, FLEXIBLE_DEFENSIVE_FREE_KICKS, context + ".budgets")
    for kind, value in raw_budgets.items():
        where = context + ".budgets." + kind
        entry = _object(value, where)
        _keys(entry, frozenset(DEFENSIVE_RESPONSIBILITIES), where)
        budgets[kind] = MappingProxyType({key: _number(n, where + "." + key) for key, n in entry.items()})
        if not isfinite(sum(budgets[kind].values()) * 104):
            raise ValueError(f"{where}: responsibility budget is too large to score safely")
    return MappingProxyType(templates), MappingProxyType(approaches), MappingProxyType(budgets)


def load_set_piece_weights(directory: Path = DATA_DIR) -> SetPieceWeights:
    """Load every family once; reject misspellings, missing jobs and ignored data."""

    model = _read(directory / "model.json")
    _keys(model, {"version", "deliveryFootBonus"}, "model.json")
    version = model["version"]
    if not isinstance(version, str) or not version.strip():
        raise ValueError("model.json.version: expected a non-empty string")
    foot_bonus = _number(model["deliveryFootBonus"], "model.json.deliveryFootBonus", allow_zero=True)
    roles, variants, tasks = {}, {}, {}
    defensive_templates, defensive_approaches, defensive_budgets = {}, {}, {}
    family_jobs = {
        "attacking_corners": _CORNER_ATTACK_JOBS,
        "defending_corners": _CORNER_DEFENCE_JOBS,
        "attacking_free_kicks": _FREE_KICK_ATTACK_JOBS,
        "defending_free_kicks": _FREE_KICK_DEFENCE_JOBS,
        "penalties": frozenset(), "long_throws": frozenset(),
    }
    expected_files = {name + ".json" for name in family_jobs} | {"model.json"}
    extra_files = {p.name for p in directory.glob("*.json")} - expected_files
    if extra_files:
        raise ValueError(f"set-piece config: unexpected files {sorted(extra_files)}")

    for family, job_keys in family_jobs.items():
        context = family + ".json"
        document = _read(directory / context)
        family_tasks = {key for key, location in _TASK_FILES.items() if location == family}
        has_variants = family.endswith("free_kicks")
        expected = {"profiles"}
        if job_keys:
            expected.add("variants" if has_variants else "roles")
        if family_tasks:
            expected.add("tasks")
        if family == "defending_free_kicks":
            expected.update(("templates", "approaches", "budgets"))
        _keys(document, expected, context)
        if family == "defending_free_kicks":
            defensive_templates, defensive_approaches, defensive_budgets = _defensive_choices(document, context)
        profiles = {}
        for key, raw in _object(document["profiles"], context + ".profiles").items():
            where = context + ".profiles." + key
            if not key.strip():
                raise ValueError(f"{context}: profile names must not be empty")
            attributes = _object(raw, where)
            if not attributes:
                raise ValueError(f"{where}: at least one weighted attribute is required")
            unknown = attributes.keys() - _ATTRIBUTES
            if unknown:
                raise ValueError(f"{where}: unknown attributes {sorted(unknown)}")
            weighted = tuple(
                RoleAttribute(name, _number(weight, where + "." + name, allow_zero=True))
                for name, weight in attributes.items()
            )
            total = sum(a.weight for a in weighted)
            if not isfinite(total) or total <= 0:
                raise ValueError(f"{where}: total attribute weight must be finite and positive")
            profiles[key] = weighted
        used = set()

        def profile(name, where):
            if not isinstance(name, str) or name not in profiles:
                raise ValueError(f"{where}: unknown profile {name!r}")
            used.add(name)
            return profiles[name]

        if family_tasks:
            raw_tasks = _object(document["tasks"], context + ".tasks")
            _keys(raw_tasks, family_tasks, context + ".tasks")
            for key, raw_task in raw_tasks.items():
                task_context = context + ".tasks." + key
                entry = _object(raw_task, task_context)
                expected = {"profile", "dedicatedProfile"} if key in _DEDICATED_TASKS else {"profile"}
                _keys(entry, expected, task_context)
                standard = profile(entry["profile"], task_context)
                dedicated = profile(entry["dedicatedProfile"], task_context) if key in _DEDICATED_TASKS else ()
                if key in _DEDICATED_TASKS and not any(
                    attribute.name == _DEDICATED_TASKS[key] and attribute.weight > 0
                    for attribute in dedicated
                ):
                    raise ValueError(f"{task_context}: dedicatedProfile must weight {_DEDICATED_TASKS[key]}")
                if key == "long_throws" and any(attribute.name != "longThrows" for attribute in standard):
                    raise ValueError(f"{task_context}: long throws must use only the longThrows rating")
                tasks[key] = TakerWeights(standard, dedicated)

        def parse_jobs(raw, where, expected_jobs=job_keys, taker_task=None):
            entries = _object(raw, where)
            _keys(entries, expected_jobs, where)
            parsed = {}
            for key, raw_job in entries.items():
                job_context = where + "." + key
                entry = _object(raw_job, job_context)
                is_taker = key in {"corner_taker", "taker"}
                _keys(entry, {"task" if is_taker else "profile", "importance"}, job_context)
                if is_taker:
                    if entry["task"] != taker_task:
                        raise ValueError(f"{job_context}: task must be {taker_task!r}")
                    attributes = tasks[taker_task].attributes
                else:
                    attributes = profile(entry["profile"], job_context)
                parsed[key] = JobWeights(
                    attributes,
                    _number(entry["importance"], job_context + ".importance"),
                )
            return MappingProxyType(parsed)

        if job_keys and has_variants:
            raw_variants = _object(document["variants"], context + ".variants")
            _keys(raw_variants, frozenset(FREE_KICK_VARIANTS), context + ".variants")
            variants[family] = MappingProxyType({
                key: parse_jobs(
                    raw_variants[key], context + ".variants." + key,
                    frozenset(DEFENSIVE_FREE_KICK_JOBS[key]) | {"keeper"} if family == "defending_free_kicks" else job_keys,
                    "direct_free_kicks" if key.startswith("direct") else "indirect_free_kicks",
                )
                for key in FREE_KICK_VARIANTS
            })
            for key, jobs in variants[family].items():
                if not isfinite(sum(job.importance for job in jobs.values()) * (100 + foot_bonus)):
                    raise ValueError(f"{context}.variants.{key}: responsibility budget is too large to score safely")
        elif job_keys:
            roles[family] = parse_jobs(document["roles"], context + ".roles", taker_task="corners")
        if unused := profiles.keys() - used:
            raise ValueError(f"{context}: unused profiles {sorted(unused)}")

    return SetPieceWeights(
        version, foot_bonus, MappingProxyType(roles), MappingProxyType(variants), MappingProxyType(tasks),
        defensive_templates, defensive_approaches, defensive_budgets,
    )


SET_PIECE_WEIGHTS = load_set_piece_weights()

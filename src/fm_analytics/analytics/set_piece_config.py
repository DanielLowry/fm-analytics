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
_FREE_KICK_DEFENCE_JOBS = frozenset(("keeper", "wall", "mark", "back", "edge", "forward"))
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


def load_set_piece_weights(directory: Path = DATA_DIR) -> SetPieceWeights:
    """Load every family once; reject misspellings, missing jobs and ignored data."""

    model = _read(directory / "model.json")
    _keys(model, {"version", "deliveryFootBonus"}, "model.json")
    version = model["version"]
    if not isinstance(version, str) or not version.strip():
        raise ValueError("model.json.version: expected a non-empty string")
    foot_bonus = _number(model["deliveryFootBonus"], "model.json.deliveryFootBonus", allow_zero=True)
    roles, variants, tasks = {}, {}, {}
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
        _keys(document, expected, context)
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
                    job_keys - {"wall"} if family == "defending_free_kicks" and key == "indirect_deep" else job_keys,
                    "direct_free_kicks" if key.startswith("direct") else "indirect_free_kicks",
                )
                for key in FREE_KICK_VARIANTS
            })
        elif job_keys:
            roles[family] = parse_jobs(document["roles"], context + ".roles", taker_task="corners")
        if unused := profiles.keys() - used:
            raise ValueError(f"{context}: unused profiles {sorted(unused)}")

    return SetPieceWeights(
        version, foot_bonus, MappingProxyType(roles), MappingProxyType(variants), MappingProxyType(tasks),
    )


SET_PIECE_WEIGHTS = load_set_piece_weights()

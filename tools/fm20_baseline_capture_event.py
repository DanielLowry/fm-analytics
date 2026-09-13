"""Validate research-only observations of FM20 baseline-helper inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass

from tools.fm20_baseline_model import adjust_baseline_level


BASELINE_HELPER_PREFIX = "FMVIS_BASELINE_HELPER "
KNOWN_CALLER_RVAS = frozenset({0x15A5606, 0x15A562C, 0x15A5789, 0x15A58D4, 0x15A5945})
BASELINE_BREAKPOINT_RVAS = {
    "FMVIS_BASELINE_SELECTOR_BREAKPOINT": 0x15A6250,
    "FMVIS_BASELINE_RATING_BREAKPOINT": 0x15A628C,
    "FMVIS_BASELINE_BONUS_BREAKPOINT": 0x15A636B,
    "FMVIS_BASELINE_RETURN_BREAKPOINT": 0x15A63A6,
    "FMVIS_DYNAMIC_SCORE_BREAKPOINT": 0x15A57EF,
}


def configure_baseline_gdb_environment(
    environment: dict[str, str], module_base: int, enabled: bool
) -> None:
    """Add the helper's verified, module-relative observation addresses."""

    environment["FMVIS_TRACE_BASELINE_HELPER"] = "1" if enabled else "0"
    for name, rva in BASELINE_BREAKPOINT_RVAS.items():
        environment[name] = hex(module_base + rva)


@dataclass(frozen=True)
class BaselineHelperEvent:
    player_id: str
    observer_address: str
    caller_rva: str
    player_selector: int
    relationship_base: int
    observer_rating: int
    relationship_bonus: bool
    baseline_knowledge: int
    dynamic_score: int | None
    relationship_source_address: str | None
    relationship_target_address: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "playerId": self.player_id,
            "observerAddress": self.observer_address,
            "callerRva": self.caller_rva,
            "playerSelector": self.player_selector,
            "relationshipBase": self.relationship_base,
            "observerRating": self.observer_rating,
            "relationshipBonus": self.relationship_bonus,
            "baselineKnowledge": self.baseline_knowledge,
            "dynamicScore": self.dynamic_score,
            "relationshipSourceAddress": self.relationship_source_address,
            "relationshipTargetAddress": self.relationship_target_address,
        }


def parse_baseline_helper_event(line: str) -> BaselineHelperEvent | None:
    """Reject extra fields and any event inconsistent with the static model."""

    if not line.startswith(BASELINE_HELPER_PREFIX):
        return None
    try:
        raw = json.loads(line.removeprefix(BASELINE_HELPER_PREFIX))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid baseline helper JSON: {exc}") from exc
    required = {
        "baseline_knowledge",
        "caller_rva",
        "dynamic_score",
        "observer_address",
        "observer_rating",
        "player_id",
        "player_selector",
        "relationship_base",
        "relationship_bonus",
        "relationship_source_address",
        "relationship_target_address",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("baseline helper event has an unexpected field contract")
    optional = {
        "dynamic_score",
        "relationship_source_address",
        "relationship_target_address",
    }
    for field in required - optional - {"relationship_bonus"}:
        if type(raw[field]) is not int or raw[field] < 0:
            raise ValueError(f"baseline helper {field} must be nonnegative")
    if type(raw["relationship_bonus"]) is not bool:
        raise ValueError("baseline helper bonus must be boolean")
    if raw["observer_address"] < 0x10000:
        raise ValueError("baseline helper observer address is invalid")
    if raw["caller_rva"] not in KNOWN_CALLER_RVAS:
        raise ValueError("baseline helper caller is outside the verified function")
    if not 0 <= raw["player_selector"] <= 127:
        raise ValueError("baseline helper selector is out of range")
    if not 0 <= raw["baseline_knowledge"] <= 100:
        raise ValueError("baseline helper result is out of range")
    dynamic_fields = tuple(raw[field] for field in optional)
    if raw["caller_rva"] == 0x15A58D4:
        if any(type(value) is not int or value < 0 for value in dynamic_fields):
            raise ValueError("dynamic baseline is missing a relationship input")
        if raw["dynamic_score"] > 100:
            raise ValueError("dynamic baseline score is out of range")
        if (
            raw["relationship_source_address"] < 0x10000
            or raw["relationship_target_address"] < 0x10000
        ):
            raise ValueError("dynamic baseline relationship address is invalid")
    elif any(value is not None for value in dynamic_fields):
        raise ValueError("fixed baseline cannot have dynamic inputs")
    expected = adjust_baseline_level(
        relationship_base=raw["relationship_base"],
        observer_rating=raw["observer_rating"],
        relationship_bonus=raw["relationship_bonus"],
    )
    if raw["baseline_knowledge"] != expected:
        raise ValueError("baseline helper result disagrees with the pure model")
    return BaselineHelperEvent(
        player_id=str(raw["player_id"]),
        observer_address=hex(raw["observer_address"]),
        caller_rva=hex(raw["caller_rva"]),
        player_selector=raw["player_selector"],
        relationship_base=raw["relationship_base"],
        observer_rating=raw["observer_rating"],
        relationship_bonus=raw["relationship_bonus"],
        baseline_knowledge=raw["baseline_knowledge"],
        dynamic_score=raw["dynamic_score"],
        relationship_source_address=(
            hex(raw["relationship_source_address"])
            if raw["relationship_source_address"] is not None
            else None
        ),
        relationship_target_address=(
            hex(raw["relationship_target_address"])
            if raw["relationship_target_address"] is not None
            else None
        ),
    )

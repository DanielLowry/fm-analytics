"""Pure, manager-visible scouting alert rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol, Sequence

from fm_analytics.analytics.scouting import contract_months_left, is_free_agent, is_transfer_listed
from fm_analytics.analytics.scouting_candidate import ScoutingCandidate
from fm_analytics.domain import Visibility
from fm_analytics.persistence import Verdict, VerdictRecord


class WeakRoleRequirements(Protocol):
    """Only the accepted weak-slot facts needed by the pure alert rules."""

    position: str
    tactic_name: str
    tactic_key: str
    role_key: str
    role_attributes: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class ScoutingAlert:
    player_id: str
    player_name: str
    reason_code: str
    reason: str
    tactic_key: str | None = None
    position: str | None = None
    role_key: str | None = None
    attributes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoutingAlerts:
    now_gettable: tuple[ScoutingAlert, ...] = ()
    rescout_due: tuple[ScoutingAlert, ...] = ()


def build_scouting_alerts(
    candidates: Sequence[ScoutingCandidate],
    previous_profiles: Mapping[str, Mapping[str, Any]],
    verdicts: Mapping[str, VerdictRecord],
    weak_slots: Sequence[WeakRoleRequirements],
    *,
    near_contract_months: int = 6,
) -> ScoutingAlerts:
    """Prepare alerts without SQL or presentation decisions."""
    if near_contract_months < 0:
        raise ValueError("a near-contract window cannot be negative")
    gettable: list[ScoutingAlert] = []
    due: list[ScoutingAlert] = []
    for candidate in candidates:
        verdict = verdicts.get(candidate.id)
        previous = previous_profiles.get(candidate.id)
        if candidate.in_current_feed and previous is not None and (
            verdict is None or verdict.verdict is not Verdict.REJECT
        ):
            reasons = _gettable_reasons(candidate, previous, near_contract_months)
            for code, reason in reasons:
                gettable.append(ScoutingAlert(candidate.id, candidate.name, code, reason))
        if verdict is not None and verdict.verdict is Verdict.WATCH:
            if candidate.history is not None and candidate.history.out_of_date:
                due.append(ScoutingAlert(
                    candidate.id, candidate.name, "stale",
                    f"Knowledge was last seen before {candidate.history.out_of_date_before}",
                ))
            for slot in weak_slots:
                if slot.position not in candidate.positions:
                    continue
                important = _important_attributes(slot.role_attributes)
                missing = tuple(
                    name for name in important
                    if name not in candidate.attributes
                    or candidate.attributes[name].visibility is Visibility.UNKNOWN
                )
                if missing:
                    due.append(ScoutingAlert(
                        candidate.id, candidate.name, "weak_role_missing",
                        f"Missing important information for {slot.tactic_name} {slot.position}",
                        slot.tactic_key, slot.position, slot.role_key, missing,
                    ))
                    break
    priority = {"became_free": 0, "became_listed": 1, "contract_near_end": 2}
    gettable.sort(key=lambda item: (priority[item.reason_code], item.player_name.casefold(), item.player_id))
    due.sort(key=lambda item: (item.reason_code != "stale", item.player_name.casefold(), item.player_id))
    return ScoutingAlerts(tuple(gettable), tuple(due))


def _gettable_reasons(
    candidate: ScoutingCandidate, previous: Mapping[str, Any], months: int
) -> tuple[tuple[str, str], ...]:
    reasons = []
    prior = replace(
        candidate, has_contract=previous.get("has_contract"),
        transfer_status=previous.get("transfer_status"),
        contract_end=previous.get("contract_end"),
        captured_game_date=previous.get("observed_on"),
    )
    if is_free_agent(candidate) and not is_free_agent(prior):
        reasons.append(("became_free", "Became a free agent"))
    if is_transfer_listed(candidate) and not is_transfer_listed(prior):
        reasons.append(("became_listed", "Became transfer listed"))
    current_months = contract_months_left(candidate)
    previous_months = contract_months_left(prior)
    if current_months is not None and current_months <= months and (
        previous_months is None or previous_months > months
    ):
        reasons.append(("contract_near_end", f"Contract entered the next {months} months"))
    return tuple(reasons)


def _important_attributes(attributes: Sequence[tuple[str, float]]) -> tuple[str, ...]:
    if not attributes:
        return ()
    highest = max(weight for _name, weight in attributes)
    return tuple(name for name, weight in attributes if weight == highest)

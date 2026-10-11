"""The League page's hidden view: its one computation and its JSON copy. HIDDEN DATA.

`build_hidden_strength_report` is the one computation behind `/league/hidden`,
and `build_hidden_strength_export` its "Copy everything as JSON". They use the
real values FM keeps for every player (`domain.hidden`), so they live apart
from `reporting.py`: the recommendation path never imports this module, and
nothing here may feed it (`tests/test_hidden_strength.py::BoundaryTests`).
See docs/hidden-attributes.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from fm_analytics.analytics import MVP_CATALOGUE, FootballCatalogue
from fm_analytics.analytics.hidden_strength import HiddenStrength, build_hidden_strength
from fm_analytics.analytics.match_roles import RoleCodes
from fm_analytics.domain.hidden import HiddenCapture
from fm_analytics.domain.matches import MatchRecord
from fm_analytics.hidden_export import hidden_document
from fm_analytics.persistence.match_history import MatchHistory
from fm_analytics.reporting import RecommendationPolicy


def hidden_seasons(history: MatchHistory) -> tuple[int, ...]:
    """The seasons of ours the hidden view can show, latest first: those with a competitive match."""
    return tuple(sorted({match.season for match in history.matches
                         if match.season is not None and not match.competition.is_friendly}, reverse=True))


def build_hidden_strength_report(
    capture: HiddenCapture,
    history: MatchHistory,
    club_matches: Sequence[MatchRecord],
    *,
    season: int | None = None,
    extra_tactic: str | None = None,
    catalogue: FootballCatalogue = MVP_CATALOGUE,
    policy: RecommendationPolicy = RecommendationPolicy(),
) -> HiddenStrength | None:
    """The one computation behind `/league/hidden`, for one season (the latest by default).

    Our competitive matches with both XIs as fielded, the league's best XIs in
    the tactics we played (plus `extra_tactic`) and in the formations each club
    played, and every club's results against what its XIs predicted.
    `club_matches` is `MatchHistoryStore.load_club_matches`. None when the
    history has no competitive season.
    """
    if capture.club.id != history.club.id:
        raise ValueError(f"the hidden-attribute read is of {capture.club.name}, the match history of {history.club.name}")
    if extra_tactic is not None and extra_tactic not in catalogue.tactics:
        raise ValueError(f"unknown tactic {extra_tactic!r}")
    seasons = hidden_seasons(history)
    if season is None:
        if not seasons:
            return None
        season = seasons[0]
    elif season not in seasons:
        raise ValueError(f"no competitive match of ours is recorded in season {season}")
    ours = [match for match in history.matches if match.season == season and not match.competition.is_friendly]
    codes = RoleCodes.build(catalogue, history.role_codes)
    tactic_keys = {}
    for match in ours:
        noted = getattr(history.notes.get(match.key), "tactic_key", None)
        if noted is None and match.detail is not None:
            noted = codes.infer_tactic(player for player in match.detail.players_for(match.side_of(history.club.id))
                                       if player.started)
        tactic_keys[match.key] = noted
    return build_hidden_strength(
        capture, ours, club_matches, our_club_id=history.club.id, season=season, our_tactic_keys=tactic_keys,
        catalogue=catalogue, extra_tactic=extra_tactic, readiness_policy=policy.readiness,
        familiarity_policy=policy.familiarity, fit_policy=policy.tactic_fit,
    )


def build_hidden_strength_export(report: HiddenStrength, *, generated_at: datetime | None = None) -> dict[str, Any]:
    """The hidden view as JSON: its "Copy everything as JSON" button."""
    return hidden_document(report, generated_at=generated_at)

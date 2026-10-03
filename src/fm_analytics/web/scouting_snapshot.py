"""Render a browser snapshot using server scores and server sort orders.

The browser only narrows and displays these rows. Changing the scoring context
(position, role, tactic or accepted visibility policy) obtains a new snapshot.
"""
from __future__ import annotations

import json
from contextvars import ContextVar

from fm_analytics.analytics.scouting import (
    SORTS_BY_MODE, contract_months_left, is_free_agent, is_transfer_listed,
    is_realistic_trial_candidate, sort_position_rankings, sort_scouting_assessments,
)
from fm_analytics.analytics.tactic_scouting import sort_tactic_assessments
from fm_analytics.web.attribute_export import candidate_export_record

SNAPSHOT = ContextVar("scouting_snapshot", default=None)


def snapshot_data(items, row_html):
    config = SNAPSHOT.get()
    mode = config["mode"]
    scored = [getattr(item, "assessment", item) for item in items]
    sorter = {"ranking": sort_position_rankings, "role": sort_scouting_assessments,
              "tactic": sort_tactic_assessments}[mode]
    orders = {
        key: {direction: [item.candidate.id for item in sorter(scored, sort=key, descending=direction == "desc")]
              for direction in ("asc", "desc")}
        for key in SORTS_BY_MODE[mode]
    }
    rows = []
    for item, rendered in zip(scored, row_html):
        c = item.candidate
        lower = item.player_fit.lower if mode == "tactic" else item.role_score.score.lower if mode == "role" else item.minimum
        upper = item.player_fit.upper if mode == "tactic" else item.role_score.score.upper if mode == "role" else item.maximum
        rows.append({
            "id": c.id, "html": rendered, "displayName": c.name, "name": c.name.casefold(), "club": (c.club or "").casefold(),
            "age": c.age, "value": c.value, "nationality": c.nationality, "footedness": c.footedness,
            "transferStatus": c.transfer_status, "availability": c.availability,
            "transferInterest": c.transfer_interest is not None, "loanInterest": c.loan_interest is not None,
            "scouted": c.is_scouted(), "current": c.in_current_feed, "search": c.in_player_search,
            "dropped": c.dropped_from_scout_reports, "captured": c.current_attributes_captured,
            "rejected": c.id in config["rejected"], "facts": dict(c.facts or {}),
            "free": is_free_agent(c), "listed": is_transfer_listed(c), "months": contract_months_left(c),
            "trial": is_realistic_trial_candidate(c), "known": item.known_attributes,
            "ranged": item.ranged_attributes, "unknown": item.unknown_attributes,
            "floor": lower, "ceiling": upper,
            "slot": item.best_slot_key if mode == "tactic" else None,
            "position": item.best_position if mode == "tactic" else None,
            "export": candidate_export_record(c, include_raw_positions=config.get("raw_positions", False)),
        })
    payload = json.dumps({"mode": mode, "orders": orders, "rows": rows}, separators=(",", ":"), ensure_ascii=True).replace("<", "\\u003c")
    return "<script type='application/json' id='scouting-snapshot'>" + payload + "</script>"

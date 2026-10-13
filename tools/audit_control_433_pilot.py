"""Read-only Hampton Control 4-3-3 checkpoint, runs 84–101.

Run: .venv/bin/python -m tools.audit_control_433_pilot
Uses the public role/clock helpers; no application or database writes.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from statistics import mean

from fm_analytics.analytics.chance_value import classify_shots
from fm_analytics.analytics.match_breakdowns import counted_split, match_clock
from fm_analytics.reporting import build_match_review, build_stored_match_report
from tools.audit_hampton_season import goal_rows, load_experiments, load_history, periods_by_score, tally_json
from tools.audit_mr_support_pilot import welch_interval

ROOT = Path(__file__).resolve().parents[1]
GROUP = "H&R - 443 DM Wide Control - Attacking"
FIELDS = ("goals", "shots", "shots_on_target", "clear_cut_chances", "crosses_attempted",
          "crosses_completed", "passes_attempted", "passes_completed", "corners")
PLAYER_FIELDS = ("goals", "shots", "shots_on_target", "clear_cut_chances", "assists",
                 "key_passes", "chances_created", "crosses_attempted", "crosses_completed")


def cohort(stored, ids, history):
    runs = [stored[i] for i in ids]
    rows = []
    for run in runs:
        own = run.side
        other = "away" if own == "home" else "home"
        detail = run.match.detail
        report = build_stored_match_report(run, history)
        row = {"id": run.id, "group": list(run.groups), "label": run.label.variant,
               "teams": {who: {k: detail.team(side).get(k) for k in FIELDS}
                         for who, side in (("us", own), ("them", other))},
               "possession": detail.possession_percent(own),
               "saved_tactic": detail.saved_tactics[own].to_document(),
               "starting_xis": {who: [{"id": p.short_id, "name": p.label, "position": p.start_position,
                                       "role": report.role_labels.get((side, p.short_id))}
                                      for p in detail.players_for(side) if p.started]
                                  for who, side in (("us", own), ("them", other))},
               "red_cards": [{"player": i.player, "minute": i.minute, "side": i.side} for i in run.match.incidents if i.kind == "sent_off"],
               "substitutions": [{"name": p.label, "minute": p.came_on} for p in detail.players_for(own) if p.came_on is not None],
               "goals_conceded": goal_rows([run.match], run.club.id),
               "goals_for": goal_rows([run.match], run.club.id, conceded=False)}
        row["scored_penalties_counted_as_ccc"] = {
            who: sum(any(e.kind == "clear_cut_chance" and e.side == side
                         and (e.minute, e.added_time, e.player_short_id)
                         == (p.minute, p.added_time, p.player_short_id) for e in detail.events)
                     for p in detail.events if p.side == side and p.kind == "penalty")
            for who, side in (("us", own), ("them", other))}
        for side in (own, other):
            team = detail.team(side)
            for key in ("crosses_attempted", "crosses_completed"):
                if key in team and (any(key not in p.stats for p in detail.players_for(side))
                                    or sum(p.stat(key) for p in detail.players_for(side)) != team[key]):
                    raise ValueError(f"{run.id}: crossing coverage/sums disagree")
        ours, theirs = row["teams"]["us"], row["teams"]["them"]
        row["net_sot"] = ours["shots_on_target"] - theirs["shots_on_target"]
        row["result"] = "W" if ours["goals"] > theirs["goals"] else "L" if ours["goals"] < theirs["goals"] else "D"
        rows.append(row)
    teams = {}
    for who in ("us", "them"):
        values = {k: [r["teams"][who][k] for r in rows if r["teams"][who][k] is not None] for k in FIELDS}
        totals = {k: sum(v) if v else None for k, v in values.items()}
        teams[who] = {"totals": totals, "means": {k: mean(v) if v else None for k, v in values.items()},
                      "coverage": {k: len(v) for k, v in values.items()},
                      "pass_completion_pct": 100 * totals["passes_completed"] / totals["passes_attempted"],
                      "cross_completion_pct": (100 * totals["crosses_completed"] / totals["crosses_attempted"]
                                               if totals["crosses_attempted"] else None)}
        penalty_ccc = sum(r["scored_penalties_counted_as_ccc"][who] for r in rows)
        teams[who]["scored_penalties_counted_as_ccc"] = penalty_ccc
        teams[who]["ccc_excluding_scored_penalties_per_game"] = (totals["clear_cut_chances"] - penalty_ccc) / len(rows)
    players = {who: defaultdict(Counter) for who in ("us", "them")}
    for run in runs:
        for who, side in (("us", run.side), ("them", "away" if run.side == "home" else "home")):
            for p in run.match.detail.players_for(side):
                if p.played:
                    players[who][p.label].update({k: p.stats[k] for k in PLAYER_FIELDS if k in p.stats})
                    players[who][p.label]["minutes"] += p.minutes
    review = build_match_review(replace(history, matches=tuple(r.match for r in runs)))
    return {"ids": list(ids), "n": len(runs), "rows": rows, "teams": teams,
            "record": dict(Counter(r["result"] for r in rows)),
            "points_per_game": mean({"W": 3, "D": 1, "L": 0}[r["result"]] for r in rows),
            "net_sot": mean(r["net_sot"] for r in rows), "mean_possession": mean(r["possession"] for r in rows),
            "players": {who: dict(counts) for who, counts in players.items()},
            "conceded_goal_types": dict(Counter(g["kind"] for r in rows for g in r["goals_conceded"])),
            "periods_by_score": periods_by_score(review.matches),
            "period_eligible_ids": [r.id for r in runs if counted_split(r.match, r.side)[0] is not None]}


def main():
    all_runs, _ = load_experiments()
    stored = {r.id: r for r in all_runs if not r.withdrawn}
    history, _ = load_history()
    ids = tuple(range(84, 92))
    if any(GROUP not in stored[i].groups for i in ids):
        raise ValueError("Expected runs not in the requested group")
    new = cohort(stored, ids, history)
    for row in new["rows"]:
        if row["saved_tactic"] != new["rows"][0]["saved_tactic"] or row["starting_xis"] != new["rows"][0]["starting_xis"]:
            raise ValueError(f"{row['id']}: tactic or starting teams differ within the new group")
    comparisons = {
        "fresh_442_balanced": tuple(range(76, 80)),
        "original_442_balanced": tuple(range(9, 17)),
        "original_442_attacking": (41, 42, 43, 45, 46, 47, 48, 49),
        "original_counter_433_positive": tuple(range(25, 33)),
        "new_without_red_90": (84, 85, 86, 87, 88, 89, 91),
        "new_first_three": (84, 85, 86),
        "new_followup_five": (87, 88, 89, 90, 91),
        "new_followup_without_red": (87, 88, 89, 91),
        "control_433_positive": tuple(range(92, 97)),
        "positive_without_red_92": (93, 94, 95, 96),
        "control_433_balanced": tuple(range(97, 102)),
    }
    windows = {name: cohort(stored, selected, history) for name, selected in comparisons.items()}
    extension_differences = {}
    for name in ("control_433_positive", "control_433_balanced"):
        group = windows[name]
        for row in group["rows"]:
            if row["saved_tactic"] != group["rows"][0]["saved_tactic"] or row["starting_xis"] != group["rows"][0]["starting_xis"]:
                raise ValueError(f"{row['id']}: tactic or starting teams differ within {name}")
        ref, observed = new["rows"][0], group["rows"][0]
        extension_differences[name] = {
            "saved_tactic_matches_attacking": observed["saved_tactic"] == ref["saved_tactic"],
            "xi_differences": {who: [{"attacking": x, "extension": y}
                                      for x, y in zip(ref["starting_xis"][who], observed["starting_xis"][who]) if x != y]
                               for who in ("us", "them")},
            "management_and_corner_parity": "Manager explicitly confirmed the same holiday route, corners, XI and instructions, changing only mentality. Balanced's recorded AMR starter contradicts the reported unchanged XI; retain that discrepancy."}
    effect = welch_interval([r["net_sot"] for r in windows["fresh_442_balanced"]["rows"]], [r["net_sot"] for r in new["rows"]])
    effect["new_minus_reference"] = effect.pop("support_minus_control")
    balanced_effect = welch_interval([r["net_sot"] for r in new["rows"]],
                                     [r["net_sot"] for r in windows["control_433_balanced"]["rows"]])
    balanced_effect["balanced_minus_attacking"] = balanced_effect.pop("support_minus_control")
    run90 = stored[90]
    clock = match_clock(run90.match, run90.side)
    fundi_kinds = Counter()
    for i in ids:
        classified = classify_shots(stored[i].match)
        if classified:
            for shot in classified:
                if shot.side == stored[i].side and shot.player_short_id == 94381:
                    fundi_kinds[(shot.kind, shot.goal)] += 1
    result = {"date": "2026-10-13", "group": GROUP,
              "input_sha256": hashlib.sha256((ROOT / "data/experiments.sqlite3").read_bytes()).hexdigest(),
              "manager_confirmation": {"source": "13 October reply: Same holiday route and corners", "same_route_and_corners_as_76_79": True,
                                       "mentality": "Attacking, per manager/group identity; unrecorded in structured labels",
                                       "additional_groups_source": "13 October answer to route/corners/XI/instructions question: Yes, only mentality changed",
                                       "additional_groups_reported_only_mentality_changed": True,
                                       "recorded_xi_discrepancy": "Balanced 97–101 starts Saydee at AMR; Attacking 84–91 and Positive 92–96 start Sankoh. Cause unresolved."},
              "new": new, "comparisons": windows, "net_sot_vs_fresh_442": effect,
              "additional_cohort_differences": extension_differences, "balanced_vs_attacking_net_sot": balanced_effect,
              "run90_before71": tally_json(clock.tally(0, 71)), "run90_after71": tally_json(clock.tally(71, clock.end)),
              "fundi_classified": [{"kind": k, "goal": g, "shots": count} for (k, g), count in fundi_kinds.items()],
              "limitations": ["Whole-package comparison: formation, passing plan, roles, personnel and mentality differ from 4-4-2.",
                              "Full result includes the red-card game; without-red figures are post-hoc sensitivity, not a substitute.",
                              "Possession is the mean of FM rounded match percentages; completion percentages pool recorded counts.",
                              "Score/period figures use the public eligibility rule, excluding whole matches with reds or extra time.",
                              "CCC adjustment removes only scored penalties with matching CCC events; missed penalties are not reliably identified.",
                              "Older group crossing is missing, not zero; differing routines/delegation context may limit old comparisons.",
                              "Eight replays of one opponent do not establish a season-wide improvement; intervals are exploratory.",
                              "Time-split on-goal geometry is distinct from FM team SOT; corners and non-goal shot origins remain incomplete."]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

"""Read-only crossing audit, accepting only recaptured matches matching the season.

Run: .venv/bin/python -m tools.audit_season_crossing
The new capture may be refused by the history's date guard. Its earlier,
unchanged fixtures can still be compared without allowing a rewind or
putting a replay into the actual season. No application/database writes.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from fm_analytics.analytics.opponent_players import where
from fm_analytics.domain.matches import MatchCapture
from tools.audit_hampton_season import goal_rows, goal_summary, load_history

ROOT = Path(__file__).resolve().parents[1]
WIDE = {"DL", "DR", "WBL", "WBR", "ML", "MR", "AML", "AMR"}
FIELDS = ("crosses_attempted", "crosses_completed", "shots", "shots_on_target",
          "clear_cut_chances", "goals", "corners", "headers_attempted", "headers_won")
PLAYER_FIELDS = ("crosses_attempted", "crosses_completed", "key_passes",
                 "chances_created", "assists", "goals")


def discrepancies(new, old):
    reasons = []
    if (new.home_goals, new.away_goals) != (old.home_goals, old.away_goals):
        reasons.append("score")
    if old.detail is None:
        return reasons + ["no detailed historical comparator"]
    for side in ("home", "away"):
        for key, value in old.detail.team(side).items():
            if new.detail.team(side).get(key) != value:
                reasons.append(f"{side} {key}")
    players = {(p.side, p.short_id): p for p in new.detail.players}
    if set(players) != {(p.side, p.short_id) for p in old.detail.players}:
        reasons.append("player identities")
    for player in old.detail.players:
        other = players.get((player.side, player.short_id))
        if other is None or any(other.stats.get(key) != value for key, value in player.stats.items()):
            reasons.append(f"player stats {player.short_id}")
    return reasons


def figures(row, games=None):
    result = dict(row)
    attempted = row["crosses_attempted"]
    result["completion_pct"] = 100 * row["crosses_completed"] / attempted if attempted else None
    if games:
        result["attempts_per_game"] = attempted / games
        result["completions_per_game"] = row["crosses_completed"] / games
    if row.get("minutes"):
        result["attempts_per90"] = attempted * 90 / row["minutes"]
        result["completions_per90"] = row["crosses_completed"] * 90 / row["minutes"]
    return result


def window(matches, club):
    totals = {who: Counter() for who in ("us", "them")}
    players = {who: defaultdict(Counter) for who in totals}
    positions = {who: defaultdict(Counter) for who in totals}
    flanks = {who: defaultdict(Counter) for who in totals}
    games = []
    for match in matches:
        own = match.side_of(club)
        game = {"key": match.key, "date": str(match.date),
                "opponent": match.team("away" if own == "home" else "home").name}
        for who, side in (("us", own), ("them", "away" if own == "home" else "home")):
            team = match.detail.team(side)
            if not all(key in team for key in ("crosses_attempted", "crosses_completed")):
                raise ValueError(f"{match.key}: crossing was not captured")
            row = {key: team[key] for key in FIELDS}
            totals[who].update(row)
            game[who] = figures(row)
            for player in match.detail.players_for(side):
                if not player.played:
                    continue
                if not all(key in player.stats for key in ("crosses_attempted", "crosses_completed")):
                    raise ValueError(f"{match.key}: {player.label} crossing was not captured")
                position, flank = where(player)
                counts = {key: player.stats.get(key, 0) for key in PLAYER_FIELDS}
                counts.update(appearances=1, minutes=player.minutes)
                players[who][player.label].update(counts)
                positions[who][position or "unknown"].update(counts)
                # Starting/played positions identify a flank, not delivery coordinates.
                if position in WIDE:
                    flanks[who][flank].update(counts)
        games.append(game)
    return {
        "games": len(matches),
        "totals": {who: figures(row, len(matches)) for who, row in totals.items()},
        "players": {who: {name: figures(row) for name, row in
                          sorted(rows.items(), key=lambda item: -item[1]["crosses_attempted"])}
                    for who, rows in players.items()},
        "positions": {who: {name: figures(row) for name, row in rows.items()}
                      for who, rows in positions.items()},
        "wide_position_flanks": {who: {name: figures(row) for name, row in rows.items()}
                                 for who, rows in flanks.items()},
        "conceded_goals": goal_summary(goal_rows(matches, club)),
        "match_rows": games,
    }


def main():
    path = ROOT / "data/match-capture.json"
    raw = path.read_bytes()
    capture = MatchCapture.from_document(json.loads(raw))
    history, _ = load_history()
    old = {match.key: match for match in history.matches}
    accepted, rejected = [], []
    for match in capture.matches:
        if match.detail is None:
            continue
        reasons = discrepancies(match, old[match.key]) if match.key in old else ["not in actual history"]
        if reasons:
            rejected.append({"key": match.key, "reasons": reasons})
        else:
            accepted.append(match)
    competitive = [m for m in accepted if not m.competition.is_friendly]
    league = [m for m in competitive if m.competition.label == "Vanarama South"]
    current_year = max(m.season for m in league)
    report = {
        "source": str(path.relative_to(ROOT)), "source_sha256": hashlib.sha256(raw).hexdigest(),
        "capture_game_date": str(capture.game_date), "accepted_detail_matches": len(accepted),
        "rejected": rejected, "club": capture.managed_club.to_document(),
        "caveats": ["Match totals do not locate crosses in time or space.",
                    "Flanks use recorded player positions, not delivery coordinates.",
                    "Cross-goal descriptors do not distinguish every corner/open-play cross.",
                    "Counts and comparisons are observational, not treatment effects."],
        "windows": {
            "current_league": window([m for m in league if m.season == current_year], history.club.id),
            "previous_league": window([m for m in league if m.season == current_year - 1], history.club.id),
            "competitive": window(competitive, history.club.id),
        },
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

"""Record FM match captures into the match history, and read the review back.

`persistence.match_history` knows how to keep matches; this module knows where
they come from (`tools/fm20_match_probe.py capture`, run read-only against the
game) and prints the same review the Matches page shows, through the one
`reporting.build_match_review` computation.

    uv run fm-matches capture            # read FM now and record what it shows
    uv run fm-matches review --group relative
    uv run fm-matches show 2019-11-02:8325133:5103652
    uv run fm-matches note 2019-11-02:8325133:5103652 --tactic vertical_442 --rating 1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.match_analysis import (
    COMPETITION_SCOPES,
    METRICS,
    MIN_GROUP_MATCHES,
    NO_TACTIC,
    GroupSummary,
    MatchReview,
    ReviewFilters,
)
from fm_analytics.analytics.match_strength import GROUPINGS
from fm_analytics.domain.matches import MatchCapture
from fm_analytics.knowledge_ingest import default_save_key
from fm_analytics.persistence.match_history import (
    MatchHistoryError,
    MatchHistoryStore,
    MatchRecordResult,
    MatchTimelineError,
)
from fm_analytics.reporting import build_match_report, build_match_review

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "match-history.sqlite3"
DEFAULT_CAPTURE = PROJECT_ROOT / "data" / "match-capture.json"
CAPTURE_TOOL = PROJECT_ROOT / "tools" / "fm20_match_probe.py"
CAPTURE_TIMEOUT_SECONDS = 120


def record_capture_file(
    store: MatchHistoryStore,
    path: str | Path,
    *,
    save_key: str | None = None,
    allow_rewind: bool = False,
) -> MatchRecordResult:
    """Read one capture file and append what it shows to `store`."""
    with Path(path).open(encoding="utf-8") as stream:
        document = json.load(stream)
    capture = MatchCapture.from_document(document)
    return store.record(capture, save_key=save_key or default_save_key(document), allow_rewind=allow_rewind)


def run_capture_tool(output: Path = DEFAULT_CAPTURE) -> str:
    """Read the running game's matches into `output`, read-only.

    The reader runs as its own process, as the scouting refresh does, so a
    problem reading FM cannot take the web server down with it.
    """
    try:
        result = subprocess.run(
            [sys.executable, str(CAPTURE_TOOL), "capture", "--output", str(output)],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
            timeout=CAPTURE_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Reading matches from FM timed out.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown failure").strip()
        raise RuntimeError(f"Matches could not be read from FM: {detail[-2_000:]}")
    return (result.stdout or "Matches captured.").strip()


def capture_and_record(
    store: MatchHistoryStore, output: Path = DEFAULT_CAPTURE, *, allow_rewind: bool = False
) -> str:
    message = run_capture_tool(output)
    result = record_capture_file(store, output, allow_rewind=allow_rewind)
    return f"{message} Recorded: {result.summary()}."


# -- text output --------------------------------------------------------------


def _number(value: float | None, percentage: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}%" if percentage else f"{value:.1f}"


def _group_line(group: GroupSummary) -> str:
    flag = "" if group.enough else "  (too few to read)"
    if not group.matches:
        return f"  {group.label:<22} no matches"
    ppg = f"{group.points_per_game:.2f}" if group.points_per_game is not None else "-"
    line = (
        f"  {group.label:<22} P{group.matches:>3} W{group.wins:>2} D{group.draws:>2} L{group.losses:>2}"
        f"  {ppg} pts/g  goals {group.goals_for}-{group.goals_against}"
    )
    if group.detailed:
        averages = "  ".join(
            f"{label.lower()} {_number(group.averages_for[key], pct)}/{_number(group.averages_against[key], pct)}"
            for key, label, pct in METRICS[:4]
        )
        line += f"  | {group.detailed} with stats: {averages}"
    return line + flag


def format_review(review: MatchReview) -> str:
    lines = [
        f"{review.club.name}: {len(review.matches)} matches "
        f"({sum(1 for s in review.matches if s.ours) } with full stats)",
        f"Grouped by: {review.grouping_label}. Figures are ours/theirs per match. "
        f"Groups under {MIN_GROUP_MATCHES} matches are too few to read.",
        "",
        _group_line(review.overall),
        *(_group_line(group) for group in review.groups),
        "",
        "By venue:",
        *(_group_line(group) for group in review.venues),
        "",
        "By tactic:",
    ]
    for row in review.tactics:
        lines.append(_group_line(replace(row.overall, label=row.label[:22])))
    goals = review.goals
    lines += [
        "",
        f"Goals by period (from {goals.goals_for_covered} of {goals.goals_for_total} scored and "
        f"{goals.goals_against_covered} of {goals.goals_against_total} conceded, full-stats matches):",
        "  " + "  ".join(f"{p}: {s}-{c}" for p, s, c in zip(goals.periods, goals.scored, goals.conceded)),
        "  Scored by: " + (", ".join(f"{label} {n}" for label, n in goals.scorers) or "-"),
        "  Made by:   " + (", ".join(f"{label} {n}" for label, n in goals.assisters) or "-"),
        "",
        "Roles (full-stats matches):",
    ]
    for role in review.roles:
        share = f"{100 * role.shot_share:.0f}% of shots" if role.shot_share is not None else "-"
        rating = f"{role.average_rating:.2f}" if role.average_rating is not None else "-"
        per_90 = role.per_90(role.shots)
        lines.append(
            f"  {role.label:<36} apps {role.appearances:>2} ({role.minutes} min)  shots {role.shots:>2} "
            f"({share}, {_number(per_90)} per 90)  goals {role.goals}  assists {role.assists}  "
            f"clear-cut {role.clear_cut_chances}  key passes {role.key_passes}  "
            f"chances created {role.chances_created}  rating {rating}"
        )
    for code in review.unconfirmed_roles:
        lines.append(f"  Unconfirmed FM role code {code.code:#x}: {code.appearances} appearances, e.g. {code.examples[0]}")
    return "\n".join(lines)


# -- command line -------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fm-matches", description="Your match history, read from FM")
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE, help="match-history database (default: %(default)s)")
    parser.add_argument("--save", help="name of this playthrough (default: the managed club's id)")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="read the running game's matches and record them")
    capture.add_argument("--output", type=Path, default=DEFAULT_CAPTURE)
    capture.add_argument("--allow-rewind", action="store_true")
    ingest = commands.add_parser("ingest", help="record capture files, oldest game date first")
    ingest.add_argument("captures", type=Path, nargs="+")
    ingest.add_argument("--allow-rewind", action="store_true")
    commands.add_parser("status", help="show what has been recorded")
    review = commands.add_parser("review", help="how matches played out, by opposition strength")
    review.add_argument("--group", choices=GROUPINGS, default="table")
    review.add_argument("--competitions", choices=COMPETITION_SCOPES, default="competitive")
    review.add_argument("--venue", choices=("home", "away"))
    review.add_argument("--tactic", help=f"a tactic key, or {NO_TACTIC!r} for matches with no known tactic")
    commands.add_parser("list", help="every recorded match")
    show = commands.add_parser("show", help="one match")
    show.add_argument("match")
    note = commands.add_parser("note", help="record the tactic you used and your pre-match rating")
    note.add_argument("match")
    note.add_argument("--tactic", help="catalogue tactic key")
    note.add_argument("--rating", type=int, help="opponent strength as you judged it before kickoff, -2..+2")
    note.add_argument("--text", default="")
    role = commands.add_parser("role-code", help="confirm which catalogue role an FM role code is")
    role.add_argument("code", help="the FM code, e.g. 0x800")
    role.add_argument("role", help="catalogue role key, e.g. af_attack")
    return parser


def _save_key(store: MatchHistoryStore, explicit: str | None) -> str:
    key = explicit or store.latest_save_key()
    if key is None:
        raise ValueError("no matches are recorded yet; run `fm-matches capture` first")
    return key


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = MatchHistoryStore(args.db)
    try:
        if args.command == "capture":
            print(capture_and_record(store, args.output, allow_rewind=args.allow_rewind))
        elif args.command == "ingest":
            for path in sorted(args.captures, key=lambda p: json.loads(p.read_text(encoding="utf-8")).get("gameDate", "")):
                result = record_capture_file(store, path, save_key=args.save, allow_rewind=args.allow_rewind)
                print(f"{path.name}: {result.summary()}")
        elif args.command == "status":
            saves = store.saves()
            if not saves:
                print(f"No matches recorded in {args.db} yet.")
            for save in saves:
                print(f"{save.key} ({save.club_name}): {save.matches} matches, {save.detailed_matches} "
                      f"with full stats, {save.captures} captures, latest {save.last_game_date}")
        elif args.command == "role-code":
            code = int(args.code, 0)
            if args.role not in MVP_CATALOGUE.roles:
                raise ValueError(f"unknown role key {args.role!r}")
            store.confirm_role_code(code, args.role)
            print(f"FM role code {code:#x} is now {MVP_CATALOGUE.roles[args.role].name}.")
        else:
            history = store.load_history(_save_key(store, args.save))
            if history is None:
                raise ValueError("that save has no recorded matches")
            if args.command == "review":
                filters = ReviewFilters(args.group, args.competitions, args.venue, args.tactic)
                print(format_review(build_match_review(history, filters=filters)))
            elif args.command == "list":
                review = build_match_review(history, filters=ReviewFilters(competitions="all"))
                for summary in review.matches:
                    stats = " full stats" if summary.ours else ""
                    print(f"{summary.match.key}  {summary.match.competition.label:<16} {summary.venue:<4} "
                          f"{summary.result} {summary.goals_for}-{summary.goals_against} v "
                          f"{summary.opponent.name} [{summary.band.label}]{stats}")
            elif args.command == "show":
                report = build_match_report(history, args.match)
                if report is None:
                    raise ValueError(f"no match {args.match}")
                print(_format_match(report))
            elif args.command == "note":
                if args.tactic and args.tactic not in MVP_CATALOGUE.tactics:
                    raise ValueError(f"unknown tactic key {args.tactic!r}")
                store.add_note(history.save_key, args.match, tactic_key=args.tactic,
                               opponent_rating=args.rating, note=args.text)
                print("Noted.")
    except (MatchHistoryError, MatchTimelineError, RuntimeError, OSError, ValueError, TypeError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


def _format_match(report) -> str:
    summary = report.summary
    match = summary.match
    strength = summary.strength
    position = (
        f"{summary.opponent.name} {strength.opponent.position} of {strength.opponent.teams}, "
        f"us {strength.ours.position}" if strength.opponent and strength.ours else "no league table"
    )
    lines = [
        f"{match.date} {match.competition.name}: {match.home.name} {match.home_goals}-{match.away_goals} {match.away.name}",
        f"At kickoff: {position} ({summary.band.label}). Tactic: "
        f"{MVP_CATALOGUE.tactics[summary.tactic_key].name if summary.tactic_key in MVP_CATALOGUE.tactics else 'not known'}"
        f"{' (from the line-up)' if summary.tactic_inferred else ''}",
    ]
    if summary.ours is None:
        lines.append("Only the result was captured for this match.")
        return "\n".join(lines)
    for key, label, pct in METRICS:
        lines.append(f"  {label:<18} {_number(summary.ours[key], pct):>6} {_number(summary.theirs[key], pct):>6}")
    for player in match.detail.players_for(summary.side):
        if player.played:
            lines.append(
                f"  {player.shirt:>2} {player.label:<24} {report.role_labels[player.role_code]:<36} "
                f"{player.minutes:>2} min  rating {_number(player.rating)}  shots {player.stat('shots')}  "
                f"goals {player.stat('goals')}  assists {player.stat('assists')}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

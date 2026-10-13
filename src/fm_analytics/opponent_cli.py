"""`fm-matches opponent`: the Opponent page's report in text, from the one `reporting.build_opponent_report`."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fm_analytics.analytics.opponent_goals import FAR_SIDE_GUESS
from fm_analytics.analytics.opponent_report import OpponentReport
from fm_analytics.domain.leagues import LeagueCapture
from fm_analytics.persistence.match_history import MatchHistory, MatchHistoryStore
from fm_analytics.reporting import build_opponent_export, build_opponent_report, opponent_choices


def _league_read(path: Path) -> LeagueCapture | None:
    """The league read, for their players' visible attributes; None without one."""
    if not path.exists():
        return None
    return LeagueCapture.from_document(json.loads(path.read_text(encoding="utf-8")))


def run_opponent(
    store: MatchHistoryStore, history: MatchHistory, *, club: str | None, window: int, before: date | None,
    league_path: Path, as_json: bool,
) -> str:
    """`fm-matches opponent`: the report on `club` (part of its name, or its FM ID), or on our next opponent."""
    fixtures = store.load_fixtures(history.save_key)
    club_id = None
    if club:
        choices = opponent_choices(history, fixtures)
        wanted = club.casefold()
        named = [choice.club for choice in choices if choice.club.id == club or wanted in choice.club.name.casefold()]
        if len(named) != 1:
            raise ValueError(
                f"{club!r} names {'no' if not named else 'more than one'} club; the league: "
                + ", ".join(choice.club.name for choice in choices)
            )
        club_id = named[0].id
    report = build_opponent_report(
        history, store.load_club_matches(history.save_key), club_id=club_id, fixtures=fixtures,
        window=window, league=_league_read(league_path), before=before,
    )
    if report is None:
        raise ValueError("no fixture of ours is recorded, so there is no next opponent: name a club, "
                         "or read matches from FM again to read its fixture list")
    if as_json:
        return json.dumps(build_opponent_export(report), indent=2, ensure_ascii=False)
    return format_opponent_report(report)


def _missing_results(count: int) -> str:
    return (f"{count} of their league results in that time {'is' if count == 1 else 'are'} not in FM's archive, "
            "so not counted.")


def format_opponent_report(report: OpponentReport) -> str:
    """The Opponent page in text: the same report, section by section."""
    evidence = report.evidence
    fixture = report.fixture
    lines = [f"Opponent report: {report.club.name}"]
    if fixture is not None:
        lines.append(f"For {fixture.home.name} v {fixture.away.name}, {fixture.date.isoformat()} ({fixture.competition.label}).")
    if report.league_position is not None:
        table = report.league_position
        lines.append(f"{report.league_name}: {table.position} of {table.teams}, {table.points} points from {table.played}.")
    if not evidence.matches:
        lines.append("No match of theirs with full stats is recorded before then.")
        return "\n".join(lines)
    lines.append(
        f"From their last {evidence.matches} competitive matches with full stats, {evidence.first} to {evidence.last}"
        + (f", {evidence.against_us} against us" if evidence.against_us else "")
        + f": scored {report.goals_for}, conceded {report.goals_against}."
        + (f" {_missing_results(evidence.league_results_missing)}" if evidence.league_results_missing else "")
    )
    lines += ["", "Form (latest first): " + "  ".join(
        f"{entry.outcome} {entry.goals_for}-{entry.goals_against} {entry.venue} {entry.opponent}" for entry in report.form)]
    if report.watch:
        lines += ["", "What to take from it:", *(f"  - {item}" for item in report.watch)]
    if report.plan is not None:
        lines += ["", f"Suggested game plan (a guess): {', '.join(plan.label for plan in report.plan.plans)}. "
                      f"They {report.plan.style}: " + "; ".join(report.plan.reasons) + "."]
    formations = report.formations
    lines += ["", f"Formation (FM names it for {formations.known} of {evidence.matches}): " + (", ".join(
        f"{use.name} {use.matches} ({use.home} home, {use.away} away)" for use in formations.uses) or "not known")]
    lines.append("  Last five: " + ", ".join(name or "?" for name in formations.recent)
                 + (f"; against us last time: {formations.against_us}" if formations.against_us else ""))
    lines += ["", "Likely XI (starts of their last five):"]
    lines += [f"  {line.position or '?':<4} {line.name:<26} {line.recent_starts}/5" for line in report.likely_xi]
    lines += ["", "Who finishes: goals (penalties, headers), shots, on target, clear-cut chances, minutes"]
    lines += [f"  {line.name:<26} {line.position or '?':<4} {line.goals:>2} ({line.penalties}p, {line.headed_goals}h)"
              f"  {line.shots:>3} {line.shots_on_target:>3} {line.clear_cut_chances:>3}  {line.minutes:>5}"
              for line in report.finishers]
    lines += ["", "Who supplies: assists (from crosses), chances created, key passes, dribbles, minutes"]
    lines += [f"  {line.name:<26} {line.position or '?':<4} {line.assists:>2} ({line.assists_from_crosses})"
              f"  {line.chances_created:>3} {line.key_passes:>3} {line.dribbles:>3}  {line.minutes:>5}"
              for line in report.suppliers]
    if report.partnerships:
        lines.append("  Partnerships: " + "; ".join(
            f"{pair.supplier} to {pair.scorer} {pair.goals}" for pair in report.partnerships))
    for title, profile in (("How they score", report.scored), ("How they concede", report.conceded)):
        lines += ["", f"{title} ({profile.goals} goals, {profile.described} with FM's description; "
                      "share, then the league's; * more or fewer than luck explains):"]
        for group in (profile.how, profile.area, profile.lines, profile.periods, profile.cross_flanks):
            lines.append("  " + "  ".join(
                f"{row.label} {row.goals}"
                + (f" ({row.share:.0%}/{row.league_share:.0%})" if row.league_share is not None and row.goals else "")
                + ("*" if row.pattern else "")
                for row in group if row.goals or row.pattern
            ))
        if profile.flank_crosses:
            lines.append(f"  Met at the far side (a guess): {profile.far_side} of {profile.flank_crosses} crosses from a flank.")
    lines += ["", "Style, per match: theirs / their opponents' / the league's (their rank)"]
    lines += [f"  {figure.label:<20} {figure.value:>6}{figure.unit} / {figure.against}{figure.unit} / "
              f"{'-' if figure.league is None else figure.league}{figure.unit}"
              + (f"  ({figure.rank} of {figure.teams})" if figure.rank else "")
              for figure in report.style]
    if report.meetings:
        lines += ["", "Against us:"]
        lines += [f"  {meeting.date} {meeting.venue} {meeting.outcome} {meeting.our_goals}-{meeting.their_goals}"
                  f"  {meeting.their_formation or '?'}  their scorers: {', '.join(meeting.their_scorers) or 'none'}"
                  for meeting in report.meetings]
    lines += ["", "Suggested opposition instructions:"]
    if not report.instructions:
        lines.append("  None: no player of theirs stands out on what FM shows.")
    for item in report.instructions:
        lines.append(f"  {item.player} ({item.position or '?'}): "
                     + ", ".join(f"{column} {value.lower()}" for column, value in item.settings))
        lines += [f"      {reason}" for reason in item.reasons]
    lines += ["", "Corners and the far side are guesses: " + FAR_SIDE_GUESS]
    return "\n".join(lines)

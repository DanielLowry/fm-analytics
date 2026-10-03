from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Sequence

from fm_analytics.api import BridgeClient, BridgeError
from fm_analytics.bridge import LinuxProtonDataSource
from fm_analytics.analytics import (
    AXIS_DEFINITIONS,
    BenchSelection,
    FORMATION_DEFINITIONS,
    MVP_CATALOGUE,
    OpponentProfile,
    RecruitmentBrief,
    ScoreBand,
    SquadDepthReport,
    TacticEvaluation,
    TacticRecommendation,
    TrainingTarget,
    WeaknessReport,
    overlay_squad_export,
    opponent_system_floors,
)
from fm_analytics.analytics.opponent import AXIS_MAXIMUM, AXIS_MINIMUM
from fm_analytics.analytics.in_transition import in_transition_selected_instructions
from fm_analytics.analytics.in_possession import in_possession_instruction_strings
from fm_analytics.analytics.out_of_possession import out_of_possession_selected_instructions
from fm_analytics.domain import GameState, Player, Squad
from fm_analytics.imports import (
    FmHtmlExport,
    merge_fm_squad_html_exports,
    parse_fm_squad_html_export,
    verify_export_completeness,
)
from fm_analytics.match_ingest import DEFAULT_DATABASE as DEFAULT_MATCH_DATABASE
from fm_analytics.persistence import SnapshotStore
from fm_analytics.persistence.match_history import MatchHistoryError, MatchHistoryStore
from fm_analytics.reporting import (
    RecommendationPolicy,
    build_recommendation_bundle,
    squad_form,
    parse_pinned_tactics,
    has_complete_role_attributes,
    required_role_attributes,
    validate_recommendation_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect the current FM squad")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--base-url",
        default="http://localhost:5072",
        help="FM bridge base URL (default: %(default)s)",
    )
    source.add_argument(
        "--fixture",
        type=Path,
        help="read a combined game/squad fixture without running the bridge",
    )
    source.add_argument(
        "--direct-live",
        action="store_true",
        help="read the managed FM20 squad directly, without starting the HTTP bridge",
    )
    parser.add_argument(
        "--fm-html",
        type=Path,
        nargs="+",
        help="validate and combine one or more manager-visible FM20 HTML exports",
    )
    parser.add_argument(
        "--recommend",
        action="store_true",
        help="recommend a tactic/XI from complete live visible attributes or --fm-html",
    )
    parser.add_argument(
        "--fm-html-player-count",
        type=int,
        help="require the merged --fm-html export to match this count shown by FM",
    )
    parser.add_argument(
        "--snapshot-db",
        type=Path,
        help="store this observation in the specified SQLite database",
    )
    parser.add_argument(
        "--my-tactics",
        metavar="KEY[,KEY...]",
        help=(
            "comma-separated tactic keys you actually play, primary first "
            "(e.g. vertical_442,wing_play_442). Bench, weaknesses, briefs and "
            "squad depth then describe these instead of the top-ranked tactic."
        ),
    )
    parser.add_argument(
        "--match-db",
        type=Path,
        default=DEFAULT_MATCH_DATABASE,
        help="match history to take each player's recent form from, when it is this club's "
        "(default: %(default)s)",
    )
    _add_opponent_arguments(parser)
    return parser


def _form_points(change: float) -> str:
    """+0.4, -0.2, or 0.0 for a change that rounds to nothing, as the Tactics page shows it."""
    return "0.0" if abs(change) < 0.05 else f"{change:+.1f}"


def recent_form(match_db: Path, game: GameState, squad: Squad):
    """Recent form from the latest save in `match_db`, as the web's Tactics page uses it."""
    if not match_db.exists():
        return None
    store = MatchHistoryStore(match_db)
    try:
        key = store.latest_save_key()
        return squad_form(store.load_history(key) if key else None, game, squad)
    except MatchHistoryError as exc:
        print(f"Recent form left out: {exc}")
        return None


def _add_opponent_arguments(parser: argparse.ArgumentParser) -> None:
    """One `--opponent-<axis>` flag per declared axis.

    Generated from `AXIS_DEFINITIONS` rather than written out, so adding a
    slider in `analytics/opponent.py` gives it a flag with no change here.
    """
    group = parser.add_argument_group(
        "opponent",
        "Your own estimate of the opposition, each -2 to +2 (0, the default, "
        "is neutral and changes nothing). These are your judgement, not "
        "measurements: nothing in FM is read to set them.",
    )
    group.add_argument(
        "--opponent-formation",
        choices=tuple(item.key for item in FORMATION_DEFINITIONS),
        default="unknown",
        help="Likely formation from your scouting report",
    )
    for axis in AXIS_DEFINITIONS:
        group.add_argument(
            f"--opponent-{axis.key.replace('_', '-')}",
            dest=f"opponent_{axis.key}",
            type=int,
            default=0,
            choices=range(AXIS_MINIMUM, AXIS_MAXIMUM + 1),
            metavar="N",
            help=f"{axis.label}: -2 = {axis.low}, +2 = {axis.high}",
        )


def opponent_from_args(args: argparse.Namespace) -> OpponentProfile:
    return OpponentProfile(
        formation=getattr(args, "opponent_formation", "unknown"),
        **{axis.key: getattr(args, f"opponent_{axis.key}", 0) for axis in AXIS_DEFINITIONS}
    )


def load_fixture(path: Path) -> tuple[GameState, Squad]:
    with path.open(encoding="utf-8") as fixture_file:
        payload = json.load(fixture_file)
    return GameState.from_dict(payload["game"]), Squad.from_dict(payload["squad"])


def render(game: GameState, squad: Squad) -> str:
    club_name = squad.club.name if squad.club else "No controlled club"
    lines = [
        f"Game date: {game.game_date.strftime('%d %B %Y')}",
        f"Manager: {game.human_manager.name}",
        f"Club: {club_name}",
        "",
        "Players",
        "-------",
    ]
    for player in squad.players:
        positions = ", ".join(player.positions)
        age = str(player.age) if player.age is not None else "?"
        condition = _percent(player.condition_percent)
        fitness = _percent(player.match_fitness_percent)
        contract = _contract_summary(player, squad)
        lines.append(
            f"{player.name:<28} age {age:<2}  {positions:<12} "
            f"condition {condition:<4} fitness {fitness:<4} "
            f"{player.availability}{contract}"
        )
    return "\n".join(lines)


def load_squad_html_import(paths: Sequence[Path]) -> FmHtmlExport:
    return merge_fm_squad_html_exports(
        tuple(
            parse_fm_squad_html_export(
                path.read_text(encoding="utf-8", errors="replace")
            )
            for path in paths
        )
    )


def render_html_import(
    paths: Sequence[Path],
    *,
    expected_players: int | None = None,
) -> str:
    combined = load_squad_html_import(paths)
    completeness = (
        verify_export_completeness(
            combined,
            expected_players=expected_players,
        )
        if expected_players is not None
        else None
    )
    counts = {"known": 0, "range": 0, "unknown": 0}
    for player in combined.players:
        for observation in player.attributes.values():
            counts[observation.visibility.value] += 1
    return "\n".join(
        (
            "FM20 manager-visible HTML import",
            "--------------------------------",
            f"Files: {len(paths)}",
            f"Unique players: {len(combined.players)}",
            f"Recognized columns: {', '.join(combined.headers)}",
            (
                "Attribute observations: "
                f"{counts['known']} exact, {counts['range']} ranged, "
                f"{counts['unknown']} unknown"
            ),
            (
                f"Completeness: verified against FM count {completeness.expected_players}"
                if completeness is not None
                else "Completeness: unverified; provide --fm-html-player-count"
            ),
        )
    )


def _opponent_lines(opponent: OpponentProfile) -> tuple[str, ...]:
    """Say what opponent was assumed, and whose judgement it is.

    Printed whenever one is set, because a reader comparing two runs needs to
    see which assumption produced which ranking.
    """
    if opponent.is_neutral:
        return ("", "Opponent: no opponent is set.")
    # The axis labels describe the -2/+2 extremes, so at one step they are
    # prefixed rather than reworded -- "leaning dominant", never the nonsense
    # that inflecting them produces ("much stronger than us, slightly").
    formation_labels = {item.key: item.label for item in FORMATION_DEFINITIONS}
    settings = (
        [f"  Likely formation: {formation_labels[opponent.formation]}"]
        if opponent.formation != "unknown"
        else []
    )
    settings.extend(
        [
        f"  {axis.label}: {value:+d} "
        f"({'' if abs(value) == 2 else 'leaning '}{axis.high if value > 0 else axis.low})"
        for axis in AXIS_DEFINITIONS
        if (value := getattr(opponent, axis.key))
        ]
    )
    # Some axes (aerial threat) only change who is picked and impose no
    # team-shape requirement. Say so, or the reader sets a slider, sees no
    # advisory check, and assumes it did nothing.
    channel = (
        "Effect: shifts which players suit each job, and sets team-shape "
        "requirements shown as an advisory check below. The check does not "
        "affect the tactic score."
        if opponent_system_floors(opponent)
        else "Effect: shifts which players suit each job. These settings impose no "
        "team-shape requirement, so no opponent check is shown."
    )
    return (
        "",
        "Assumed opponent (your estimate, not measured from the game)",
        *settings,
        channel,
    )


def render_recommendation(
    game: GameState,
    squad: Squad,
    recommendation: TacticRecommendation,
    bench: BenchSelection,
    weakness_report: WeaknessReport,
    briefs: tuple[RecruitmentBrief, ...],
    training_targets: tuple[TrainingTarget, ...] = (),
    squad_depth: SquadDepthReport | None = None,
    opponent: OpponentProfile = OpponentProfile.neutral(),
    primary: TacticEvaluation | None = None,
    pinned_keys: tuple[str, ...] = (),
) -> str:
    # `primary` is the pinned tactic the bench, weaknesses and briefs below were
    # computed for; it defaults to the top-ranked tactic when nothing is pinned.
    selected = primary if primary is not None else recommendation.selected
    club_name = squad.club.name if squad.club else "No controlled club"
    lines = [
        f"MVP recommendation for {club_name} on {game.game_date.isoformat()}",
    ]
    required_attributes = required_role_attributes()
    missing_attributes = tuple(
        sorted(
            {
                name
                for player in squad.players
                for name in required_attributes.difference(player.attributes)
            }
        )
    )
    lines.append(
        f"Attribute coverage: {len(required_attributes) - len(missing_attributes)}"
        f"/{len(required_attributes)} role inputs"
    )
    if missing_attributes:
        lines.extend(
            (
                "Warning: partial squad export; football scores are provisional.",
                "Missing role inputs: " + ", ".join(missing_attributes),
            )
        )
    else:
        lines.append("Attribute coverage: complete")
    lines.extend(
        (
        "",
        "Tactic comparison",
        "-----------------",
        "Fit: balanced player score × tactic-balance multiplier. "
        "The player score rises in direct proportion when every player improves, "
        "and rewards a more even XI.",
        )
    )
    lines.extend(_opponent_lines(opponent))
    if pinned_keys:
        lines.append("* = pinned with --my-tactics; the first pinned tactic is your primary.")
    for evaluation in recommendation.evaluations:
        marker = ("* " if evaluation.tactic.key in pinned_keys else "  ") if pinned_keys else ""
        status = "legal XI" if evaluation.has_legal_xi else (
            "missing " + ", ".join(slot.key for slot in evaluation.unfilled_slots)
        )
        lines.append(
            f"{marker}{evaluation.tactic.name:<26} "
            f"fit {_band(evaluation.score):<22} "
            f"players {evaluation.xi_score.central:.1f}, "
            f"balance ×{evaluation.tactic_balance_multiplier:.3f}"
            + (
                f", advisory opponent check {evaluation.opponent_fit.score:.1f}"
                if evaluation.opponent_fit.active
                else ""
            )
            + (
                "; role-balance warning: "
                + ", ".join(
                    evaluation.coherence.shortfalls
                    + evaluation.instruction_suitability.shortfalls
                )
                if evaluation.coherence.shortfalls
                or evaluation.instruction_suitability.shortfalls
                else ""
            )
            + f"; mean {evaluation.mean_score.central:.1f}, "
            f"weakest {evaluation.weakest_score.central:.1f} "
            f"({', '.join(evaluation.weakest_slot_keys)}); {status}"
        )
    lines.extend(("", "Training targets", "-----------------"))
    if training_targets:
        lines.append(
            "Tactics worth training towards, ranked by potential fit once "
            "position familiarity is no longer the limiting factor:"
        )
        for target in training_targets:
            lines.append(
                f"{target.tactic_name:<26} "
                f"effective {target.effective_score.central:.1f} -> "
                f"potential {target.potential_score.central:.1f} "
                f"(+{target.score_gap:.1f})"
            )
    else:
        lines.append(
            "No tactic's potential fit clears its effective fit by a material margin."
        )
    top_ranked = recommendation.selected
    heading = (
        f"Primary (pinned): {selected.tactic.name} ({selected.tactic.formation})"
        if pinned_keys
        else f"Selected: {selected.tactic.name} ({selected.tactic.formation})"
    )
    lines.extend(("", heading))
    if pinned_keys and top_ranked.tactic.key != selected.tactic.key:
        lines.append(
            f"Highest fit overall: {top_ranked.tactic.name} "
            f"({_band(top_ranked.score)}) vs primary {_band(selected.score)}."
        )
    lines.extend(
        (
            f"Mentality: {selected.tactic.mentality}",
            "Instructions: " + "; ".join(
                selected.tactic.instructions
                + in_possession_instruction_strings(selected.tactic.in_possession)
                + in_transition_selected_instructions(selected.tactic.in_transition)
                + out_of_possession_selected_instructions(selected.tactic.out_of_possession)
            ),
            "",
            "Starting XI" if selected.has_legal_xi else "Best feasible partial XI",
            "-----------" if selected.has_legal_xi else "------------------------",
        )
    )
    for assignment in selected.assignments:
        all_warnings = assignment.readiness_warnings + assignment.familiarity_warnings
        warnings = f"; {', '.join(all_warnings)}" if all_warnings else ""
        lines.append(
            f"{assignment.slot.key:<5} {assignment.player_name:<28} "
            f"{assignment.intrinsic_role_score.role_name:<34} "
            f"role {_band(assignment.intrinsic_role_score.score)}, "
            f"readiness -{assignment.readiness_penalty:.1f}, "
            f"familiarity x{assignment.familiarity_multiplier:.2f}, "
            + (f"form {_form_points(assignment.form_change)}, " if assignment.form_multiplier != 1.0 else "")
            + f"selection {assignment.selection_score.central:.1f}{warnings}"
        )
    if selected.unfilled_slots:
        lines.append(
            "Unfilled: "
            + ", ".join(
                f"{slot.key} ({slot.position}, {slot.role_key})"
                for slot in selected.unfilled_slots
            )
        )
    lines.extend(("", "Substitutes", "-----------"))
    if bench.entries:
        for priority, entry in enumerate(bench.entries, start=1):
            primary = entry.primary_assignment
            warnings = (
                f"; {', '.join(primary.readiness_warnings)}"
                if primary.readiness_warnings
                else ""
            )
            lines.append(
                f"{priority}. {entry.player_name:<25} primary {primary.slot.key} "
                f"({primary.intrinsic_role_score.role_name}, "
                f"selection {primary.selection_score.central:.1f}); "
                f"credible {', '.join(entry.credible_slots) or 'none'}; "
                f"can fill {', '.join(entry.covered_slots)}{warnings}"
            )
    else:
        lines.append("No selectable non-starter is available.")
    if bench.uncovered_slots:
        lines.append("Bench coverage gaps: " + ", ".join(bench.uncovered_slots))
    if bench.weakly_covered_slots:
        lines.append(
            "Below-threshold bench cover: "
            + ", ".join(bench.weakly_covered_slots)
            + f" (best option below {bench.credible_cover_ratio:.0%} of the starter)"
        )
    lines.append(
        f"Versions: catalogue {selected.tactic.catalogue_version}; "
        f"readiness {selected.readiness_version}; fit {selected.fit_version}; "
        f"bench {bench.policy_version}"
    )
    lines.extend(("", "Weak points", "-----------"))
    if weakness_report.weaknesses:
        lines.extend(
            f"[{weakness.kind.value}] {weakness.message}"
            for weakness in weakness_report.weaknesses
        )
    else:
        lines.append("No threshold weakness identified.")
    if squad_depth is not None:
        depth_heading = (
            f"Squad depth across your {len(pinned_keys)} pinned tactic(s)"
            if pinned_keys
            else "Squad depth across evaluated tactics"
        )
        lines.extend(
            (
                "",
                depth_heading,
                "-" * len(depth_heading),
                "A position is 'persistent' when it is weak in every evaluated "
                "tactic that fields it, and 'occasional' when only some.",
            )
        )
        if squad_depth.persistent_weaknesses:
            lines.append("Persistent:")
            lines.extend(
                f"  {depth.position}: weak in all {len(depth.tactics_with_this_position)} "
                f"tactic(s) that use it"
                for depth in squad_depth.persistent_weaknesses
            )
        if squad_depth.occasional_weaknesses:
            lines.append("Occasional:")
            lines.extend(
                f"  {depth.position}: weak in {len(depth.tactics_with_a_weakness)} of "
                f"{len(depth.tactics_with_this_position)} tactic(s) that use it"
                for depth in squad_depth.occasional_weaknesses
            )
        if not squad_depth.persistent_weaknesses and not squad_depth.occasional_weaknesses:
            lines.append("No position is weak across the evaluated tactics.")
    lines.extend(("", "Recruitment briefs", "------------------"))
    if briefs:
        lines.extend(
            f"{brief.need}: {brief.position} / {brief.role_key} "
            f"target {brief.minimum_role_score:.1f} — {brief.reason}"
            for brief in briefs
        )
        lines.append("For candidates against each brief, see fm-web's /scouting page.")
    else:
        lines.append("No permanent recruitment brief generated.")
    return "\n".join(lines)


def _band(value: ScoreBand) -> str:
    return f"{value.lower:.1f}/{value.central:.1f}/{value.upper:.1f}"


def _percent(value: int | None) -> str:
    return f"{value}%" if value is not None else "?"


def _contract_summary(player: Player, squad: Squad) -> str:
    contract = player.contract
    contracted_club = contract.contracted_club if contract else None
    if contracted_club and squad.club and contracted_club.id != squad.club.id:
        return f" · loan from {contracted_club.name}"
    return ""




def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        pinned_tactics = parse_pinned_tactics(args.my_tactics)
        if pinned_tactics and not args.recommend:
            raise ValueError("--my-tactics requires --recommend")
        if args.fm_html_player_count is not None and not args.fm_html:
            raise ValueError("--fm-html-player-count requires --fm-html")
        if args.fm_html and not args.recommend:
            if args.snapshot_db:
                raise ValueError("--snapshot-db requires --recommend with --fm-html")
            output = render_html_import(
                args.fm_html,
                expected_players=args.fm_html_player_count,
            )
            game = squad = capture = None
        else:
            if args.fixture:
                game, squad = load_fixture(args.fixture)
                source_name = "fixture"
            else:
                live_source = (
                    LinuxProtonDataSource() if args.direct_live
                    else BridgeClient(args.base_url)
                )
                if args.direct_live:
                    game, squad = live_source.read_snapshot()
                    source_name = live_source.name
                else:
                    health = live_source.get_health()
                    if not health.is_ready:
                        raise BridgeError(health.detail or health.status)
                    game, squad = live_source.get_game(), live_source.get_squad()
                    source_name = health.source
            recommendation = None
            primary = None
            training_targets = ()
            bench = None
            weakness_report = None
            squad_depth = None
            briefs = ()
            if args.recommend:
                validate_recommendation_snapshot(game, squad)
                if args.fm_html:
                    squad_export = load_squad_html_import(args.fm_html)
                    if args.fm_html_player_count is not None:
                        verify_export_completeness(
                            squad_export,
                            expected_players=args.fm_html_player_count,
                        )
                    merged = overlay_squad_export(squad, squad_export)
                    squad = merged.squad
                    source_name = f"{source_name}+fm20-ui-html"
                elif not has_complete_role_attributes(squad):
                    raise ValueError(
                        "--recommend requires complete manager-visible squad attributes; "
                        "the current source is incomplete"
                    )
                bundle = build_recommendation_bundle(
                    game,
                    squad,
                    catalogue=MVP_CATALOGUE,
                    policy=RecommendationPolicy(
                        opponent=opponent_from_args(args),
                        pinned_tactics=pinned_tactics,
                    ),
                    form=recent_form(args.match_db, game, squad),
                )
                recommendation = bundle.recommendation
                training_targets = bundle.training_targets
                bench = bundle.bench
                weakness_report = bundle.weakness_report
                squad_depth = bundle.planning_depth
                primary = bundle.primary
                briefs = bundle.briefs
            capture = (
                SnapshotStore(args.snapshot_db).capture(
                    game,
                    squad,
                    source=source_name,
                )
                if args.snapshot_db
                else None
            )
    except (
        BridgeError,
        OSError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ) as exc:
        print(f"error: {exc}")
        return 1

    if args.fm_html and not args.recommend:
        print(output)
        return 0

    assert game is not None
    assert squad is not None
    if recommendation is not None:
        assert weakness_report is not None
        assert bench is not None
        print(
            render_recommendation(
                game,
                squad,
                recommendation,
                bench,
                weakness_report,
                briefs,
                training_targets,
                squad_depth,
                opponent=opponent_from_args(args),
                primary=primary,
                pinned_keys=pinned_tactics,
            )
        )
    else:
        print(render(game, squad))
    if capture is not None:
        action = "created" if capture.created else "reused"
        print(f"\nSnapshot: {action} capture {capture.id} in {args.snapshot_db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

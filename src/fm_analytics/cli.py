from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Sequence

from fm_analytics.api import BridgeClient, BridgeError
from fm_analytics.bridge import LinuxProtonDataSource
from fm_analytics.analytics import (
    BenchSelection,
    MVP_CATALOGUE,
    RecruitmentBrief,
    RecruitmentShortlist,
    ScoreBand,
    SquadDepthReport,
    TacticRecommendation,
    TrainingTarget,
    WeaknessReport,
    overlay_squad_export,
    shortlist_candidates,
)
from fm_analytics.domain import GameState, Player, Squad
from fm_analytics.imports import (
    FmHtmlExport,
    merge_fm_html_exports,
    merge_fm_squad_html_exports,
    parse_fm_html_export,
    parse_fm_squad_html_export,
    verify_export_completeness,
)
from fm_analytics.persistence import SnapshotStore
from fm_analytics.reporting import (
    build_recommendation_bundle,
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
        "--candidate-html",
        type=Path,
        nargs="+",
        help="optional manager-visible Player Search exports for recruitment shortlists",
    )
    parser.add_argument(
        "--candidate-player-count",
        type=int,
        help="required FM-visible row count for --candidate-html completeness",
    )
    parser.add_argument(
        "--snapshot-db",
        type=Path,
        help="store this observation in the specified SQLite database",
    )
    return parser


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


def load_html_import(paths: Sequence[Path]) -> FmHtmlExport:
    return merge_fm_html_exports(
        tuple(
            parse_fm_html_export(
                path.read_text(encoding="utf-8", errors="replace")
            )
            for path in paths
        )
    )


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


def render_recommendation(
    game: GameState,
    squad: Squad,
    recommendation: TacticRecommendation,
    bench: BenchSelection,
    weakness_report: WeaknessReport,
    briefs: tuple[RecruitmentBrief, ...],
    shortlists: tuple[RecruitmentShortlist, ...],
    training_targets: tuple[TrainingTarget, ...] = (),
    squad_depth: SquadDepthReport | None = None,
) -> str:
    selected = recommendation.selected
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
        f"Fit: {(1 - selected.fit_weakest_weight) * 100:.0f}% XI mean + "
        f"{selected.fit_weakest_weight * 100:.0f}% weakest slot, after readiness; "
        "an unfilled slot scores 0.",
        )
    )
    for evaluation in recommendation.evaluations:
        status = "legal XI" if evaluation.has_legal_xi else (
            "missing " + ", ".join(slot.key for slot in evaluation.unfilled_slots)
        )
        lines.append(
            f"{evaluation.tactic.name:<26} "
            f"fit {_band(evaluation.score):<22} "
            f"mean {evaluation.mean_score.central:.1f}, "
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
    lines.extend(
        (
            "",
            f"Selected: {selected.tactic.name} ({selected.tactic.formation})",
            f"Mentality: {selected.tactic.mentality}",
            "Instructions: " + "; ".join(selected.tactic.instructions),
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
            f"selection {assignment.selection_score.central:.1f}{warnings}"
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
        for entry in bench.entries:
            primary = entry.primary_assignment
            warnings = (
                f"; {', '.join(primary.readiness_warnings)}"
                if primary.readiness_warnings
                else ""
            )
            lines.append(
                f"{entry.player_name:<28} primary {primary.slot.key} "
                f"({primary.intrinsic_role_score.role_name}, "
                f"selection {primary.selection_score.central:.1f}); "
                f"covers {', '.join(entry.covered_slots)}{warnings}"
            )
    else:
        lines.append("No selectable non-starter is available.")
    if bench.uncovered_slots:
        lines.append("Bench coverage gaps: " + ", ".join(bench.uncovered_slots))
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
        lines.extend(
            (
                "",
                "Squad depth across evaluated tactics",
                "-------------------------------------",
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
    else:
        lines.append("No permanent recruitment brief generated.")
    for shortlist in shortlists:
        brief = shortlist.brief
        lines.extend(
            (
                "",
                f"Candidates for {brief.position} / {brief.role_key}",
                "-" * (15 + len(brief.position) + len(brief.role_key)),
            )
        )
        if not shortlist.candidates:
            lines.append("No exported candidate can reach the threshold.")
            continue
        for candidate in shortlist.candidates[:10]:
            scouting = (
                f"; scout more: {', '.join(candidate.scout_more)}"
                if candidate.scout_more
                else ""
            )
            lines.append(
                f"{candidate.player_name:<28} {_band(candidate.role_score.score)} "
                f"{candidate.verdict.value}{scouting}"
            )
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
        if args.fm_html_player_count is not None and not args.fm_html:
            raise ValueError("--fm-html-player-count requires --fm-html")
        if args.candidate_html and not args.recommend:
            raise ValueError("--candidate-html requires --recommend")
        if args.candidate_html and args.candidate_player_count is None:
            raise ValueError(
                "--candidate-html requires --candidate-player-count from the FM UI"
            )
        if args.candidate_player_count is not None and not args.candidate_html:
            raise ValueError("--candidate-player-count requires --candidate-html")
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
                health = live_source.get_health()
                if not health.is_ready:
                    raise BridgeError(health.detail or health.status)
                game, squad = live_source.get_game(), live_source.get_squad()
                source_name = health.source
            recommendation = None
            training_targets = ()
            bench = None
            weakness_report = None
            squad_depth = None
            briefs = ()
            shortlists = ()
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
                bundle = build_recommendation_bundle(game, squad, catalogue=MVP_CATALOGUE)
                recommendation = bundle.recommendation
                training_targets = bundle.training_targets
                bench = bundle.bench
                weakness_report = bundle.weakness_report
                squad_depth = bundle.squad_depth
                briefs = bundle.briefs
                if args.candidate_html:
                    candidate_export = load_html_import(args.candidate_html)
                    verify_export_completeness(
                        candidate_export,
                        expected_players=args.candidate_player_count,
                    )
                    squad_ids = frozenset(player.id for player in squad.players)
                    shortlists = tuple(
                        shortlist_candidates(
                            brief,
                            candidate_export.players,
                            MVP_CATALOGUE,
                            excluded_player_ids=squad_ids,
                        )
                        for brief in briefs
                    )
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
                shortlists,
                training_targets,
                squad_depth,
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

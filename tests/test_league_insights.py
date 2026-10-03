import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fm_analytics.analytics.league_comparison import build_league_report
from fm_analytics.analytics.league_insights import (
    TeamSummary,
    _team_score,
    coverage,
    knowledge_level,
    league_priorities,
    scouting_priorities,
    team_change,
    xi_difference,
)
from fm_analytics.analytics.role_scoring import ScoreBand
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.persistence.league_history import MIGRATIONS, LeagueHistoryStore
from fm_analytics.persistence.migrations import bring_up_to_date
from fm_analytics.reporting import league_scope
from tests.league_support import league_capture, small_catalogue


def team(report, club_id):
    return next(t for t in report.teams if t.roster.squad.club.id == club_id)


def known(value):
    return AttributeObservation(Visibility.KNOWN, value=value)


class ScoutingPriorityTests(unittest.TestCase):
    def setUp(self):
        self.capture, self.catalogue = league_capture(), small_catalogue()
        self.report = build_league_report(self.capture, self.catalogue)
        self.unknown = team(self.report, "rival-2")

    def test_the_stake_formula_is_the_scorers_own_team_score(self):
        for scenario, end in (("upper", "upper"), ("lower", "lower")):
            evaluation = getattr(self.unknown.comparison, scenario).selected
            values = [getattr(item.selection_score, end) for item in evaluation.assignments]
            self.assertAlmostEqual(_team_score(evaluation, values), getattr(evaluation.score, end), places=3)

    def test_each_stake_is_the_fixed_xi_drop_for_that_one_player(self):
        upper = self.unknown.comparison.upper.selected
        row = self.unknown.priorities[0]
        values = [item.selection_score.lower if item.player_id == row.player_id else item.selection_score.upper
                  for item in upper.assignments]
        self.assertAlmostEqual(row.ceiling_at_stake, upper.score.upper - _team_score(upper, values), places=2)
        self.assertGreater(row.ceiling_at_stake, row.floor_at_stake)
        self.assertTrue(row.attributes)

    def test_a_reserve_who_could_cover_the_slot_limits_what_rests_on_the_starter(self):
        rival = self.capture.teams[2]
        starter = rival.squad.players[0]
        reserve = replace(starter, id="rival-2-reserve", name="Known reserve",
                          attributes={key: known(12) for key in starter.attributes})
        covered = replace(self.capture, teams=self.capture.teams[:2] + (replace(rival, squad=replace(
            rival.squad, players=rival.squad.players + (reserve,))),) + self.capture.teams[3:])
        report = build_league_report(covered, self.catalogue)
        upper = team(report, "rival-2").comparison.upper.selected
        starter_slot = next(item.slot.key for item in upper.assignments if item.player_id == starter.id)
        before = next(row for row in self.unknown.priorities if row.player_id == starter.id).ceiling_at_stake
        after = next(row for row in team(report, "rival-2").priorities if row.player_id == starter.id)
        self.assertLess(after.ceiling_at_stake, before)
        cover = next(option for option in team(report, "rival-2").alternatives["upper"][starter_slot]
                     if option.player_id == reserve.id)
        values = [cover.selection_score.upper if item.slot.key == starter_slot else item.selection_score.upper
                  for item in upper.assignments]
        self.assertAlmostEqual(after.ceiling_at_stake, upper.score.upper - _team_score(upper, values), places=2)

    def test_known_squads_and_our_own_club_have_nothing_to_learn(self):
        self.assertEqual(team(self.report, "rival-1").priorities, ())
        self.assertEqual(team(self.report, "club-100").priorities, ())
        self.assertEqual(team(self.report, "rival-3").priorities, ())  # unscored: shown its gaps instead

    def test_only_a_player_who_alone_could_settle_the_comparison_is_marked(self):
        ceiling = self.unknown.score.upper
        self.assertTrue(all(not row.settles for row in self.unknown.priorities))  # we are far below their ceiling
        close = scouting_priorities(self.unknown, ScoreBand(ceiling - 1, ceiling - 1, ceiling - 1))
        self.assertEqual(close[0].settles, "could show they cannot reach your score")
        above = scouting_priorities(self.unknown, ScoreBand(0.05, 0.05, 0.1))
        self.assertEqual(above[0].settles, "could show they are above you")
        self.assertTrue(all(not row.settles for row in scouting_priorities(self.unknown, None)))

    def test_league_shortlist_puts_decisive_players_first(self):
        rows = league_priorities(self.report, limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual({row.club_id for row in rows}, {"rival-2"})


class KnowledgeAndDifferenceTests(unittest.TestCase):
    def test_knowledge_levels_and_coverage(self):
        ranged = AttributeObservation(Visibility.RANGE, minimum=8, maximum=12)
        unknown = AttributeObservation(Visibility.UNKNOWN)
        self.assertEqual(knowledge_level([known(10), known(12)]), "known")
        self.assertEqual(knowledge_level([known(10), ranged]), "partly known")
        self.assertEqual(knowledge_level([unknown, None]), "unknown")
        self.assertEqual(coverage([known(10), ranged, unknown, None, None]), (1, 1, 1, 2))

    def test_starters_are_counted_in_the_conservative_xi(self):
        report = build_league_report(league_capture(), small_catalogue())
        self.assertEqual(team(report, "rival-1").starters, (11, 0, 0))
        self.assertEqual(team(report, "rival-2").starters, (0, 0, 11))

    def test_xi_difference_names_the_changed_players_and_system(self):
        report = build_league_report(league_capture(), small_catalogue())
        central = team(report, "rival-1").comparison.central.selected
        self.assertTrue(xi_difference(central, central).same)
        fewer = replace(central, assignments=central.assignments[1:])
        difference = xi_difference(fewer, central)
        self.assertEqual(difference.players_in, (central.assignments[0].player_name,))
        self.assertEqual((difference.players_out, difference.tactic), ((), ""))


class ChangeTests(unittest.TestCase):
    def summary(self, **changes):
        base = TeamSummary("c1", "Club", "ready", ScoreBand(10, 12, 20), "Balanced 4-4-2",
                           (("1", "Alpha"), ("2", "Beta")), date(2020, 5, 1))
        return replace(base, **changes)

    def test_document_round_trip(self):
        self.assertEqual(TeamSummary.from_document(self.summary().to_document()), self.summary())
        unscored = self.summary(score=None, status="no_legal_xi", tactic="")
        self.assertEqual(TeamSummary.from_document(unscored.to_document()), unscored)

    def test_no_change_is_none_and_each_kind_of_change_is_named(self):
        self.assertIsNone(team_change(self.summary(), self.summary(game_date=date(2020, 5, 8))))
        change = team_change(self.summary(), self.summary(score=ScoreBand(11, 13, 18), tactic="Vertical 4-4-2",
                                                          xi=(("1", "Alpha"), ("3", "Gamma"))))
        self.assertEqual((change.since, change.tactic), (date(2020, 5, 1), "Vertical 4-4-2"))
        self.assertEqual((change.players_in, change.players_out), (("Gamma",), ("Beta",)))
        status = team_change(self.summary(score=None, status="positions_incomplete", tactic=""), self.summary())
        self.assertEqual(status.previous_status, "positions_incomplete")


class TeamCacheTests(unittest.TestCase):
    def test_only_clubs_whose_inputs_changed_are_recomputed(self):
        capture, catalogue, cache = league_capture(), small_catalogue(), {}
        first = build_league_report(capture, catalogue, team_cache=cache)
        self.assertEqual(len(cache), 4)
        later = replace(capture, game=replace(capture.game, game_date=capture.game.game_date + timedelta(days=7)),
                        teams=tuple(replace(r, squad=replace(r.squad, as_of_date=r.squad.as_of_date + timedelta(days=7)))
                                    for r in capture.teams))
        rival = later.teams[2]
        player = rival.squad.players[0]
        scouted = replace(player, attributes={**player.attributes, "passing": known(15)})
        later = replace(later, teams=later.teams[:2] + (replace(rival, squad=replace(
            rival.squad, players=(scouted,) + rival.squad.players[1:])),) + later.teams[3:])
        with patch("fm_analytics.analytics.league_comparison.compare_team_xi",
                   wraps=__import__("fm_analytics.analytics.league_comparison", fromlist=["x"]).compare_team_xi) as compute:
            second = build_league_report(later, catalogue, team_cache=cache, previous=first.summaries())
        self.assertEqual(compute.call_count, 1)  # only the newly scouted club
        self.assertEqual(team(second, "rival-1").roster.squad.as_of_date, later.game.game_date)
        self.assertEqual(team(second, "rival-1").score, team(first, "rival-1").score)
        self.assertIsNone(team(second, "rival-1").change)
        change = team(second, "rival-2").change
        self.assertIsNotNone(change)
        self.assertGreater(change.current.lower, change.previous.lower)


class SummaryHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "league.sqlite3"
        self.capture = league_capture()
        self.report = build_league_report(self.capture, small_catalogue())

    def test_a_version_1_history_is_upgraded_in_place_with_a_backup(self):
        with sqlite3.connect(self.path) as connection:
            bring_up_to_date(connection, self.path, MIGRATIONS[:1], kind="league-history", error=RuntimeError)
        store = LeagueHistoryStore(self.path)
        store.record(self.capture)
        store.record_summaries(self.capture, "best|x", self.report.summaries())
        self.assertTrue(self.path.with_name(self.path.name + ".bak-v1").exists())

    def test_previous_summaries_come_from_the_latest_other_read_in_the_same_scope(self):
        store = LeagueHistoryStore(self.path)
        store.record(self.capture)
        store.record_summaries(self.capture, "best|x", self.report.summaries())
        self.assertEqual(store.previous_summaries(self.capture, "best|x"), {})  # only itself so far
        revised = replace(self.capture, membership_evidence="Revised the same day")
        store.record(revised)
        previous = store.previous_summaries(revised, "best|x")
        self.assertEqual(previous, self.report.summaries())
        self.assertEqual(store.previous_summaries(revised, "balanced_442|x"), {})

    def test_summaries_need_their_capture(self):
        with self.assertRaises(RuntimeError):
            LeagueHistoryStore(self.path).record_summaries(self.capture, "best|x", {})

    def test_scope_changes_with_the_model_and_the_tactic_choice(self):
        self.assertNotEqual(league_scope(None), league_scope("balanced_442"))
        self.assertNotEqual(league_scope(None), league_scope(None, catalogue=small_catalogue()))
        self.assertEqual(league_scope(None), league_scope(None))


if __name__ == "__main__":
    unittest.main()

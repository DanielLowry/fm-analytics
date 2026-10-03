import unittest
from dataclasses import replace

from fm_analytics.analytics import PlayerSelectionInput, recommend_tactic
from fm_analytics.analytics.league_comparison import build_league_report, order_teams, rank_team_players, team_information_gaps
from fm_analytics.domain import AttributeObservation, Visibility
from tests.league_support import league_capture, small_catalogue


class LeagueComparisonTests(unittest.TestCase):
    def setUp(self):
        self.capture = league_capture()
        self.catalogue = small_catalogue()
        self.report = build_league_report(self.capture, self.catalogue)

    def team(self, club_id, report=None):
        return next(t for t in (report or self.report).teams if t.roster.squad.club.id == club_id)

    def test_owned_central_selection_matches_the_existing_neutral_path(self):
        owned = self.capture.teams[0].squad
        existing = recommend_tactic(tuple(PlayerSelectionInput.from_player(p) for p in owned.players), self.catalogue)
        actual = self.team(owned.club.id)
        self.assertEqual(actual.comparison.central.selected, existing.selected)
        self.assertEqual(actual.score.lower, actual.score.upper)
        self.assertEqual(actual.relative_to_us, "Your club")

    def test_intervals_leave_unknown_clubs_unresolved_and_exclude_incomplete_clubs(self):
        strong, unknown, partial = (self.team(f"rival-{i}") for i in (1, 2, 3))
        self.assertEqual((strong.rank_lower, strong.rank_upper), (1, 2))
        self.assertEqual((unknown.rank_lower, unknown.rank_upper), (1, 3))
        self.assertEqual(unknown.relative_to_us, "Overlapping")
        self.assertIsNone(partial.score)
        self.assertIsNone(partial.rank_lower)
        self.assertEqual(self.report.comparable_count, 3)
        self.assertEqual(order_teams(self.report.teams, "uncertainty")[0], unknown)
        self.assertEqual(order_teams(self.report.teams, "upper")[-1], partial)

    def test_exact_ties_share_rank_even_when_another_club_is_unknown(self):
        strong = self.capture.teams[1]
        partial = self.capture.teams[3]
        tied = replace(partial, roster_complete=True,
                       squad=replace(partial.squad, players=tuple(replace(p, attributes=strong.squad.players[0].attributes)
                                                                 for p in partial.squad.players)))
        report = build_league_report(replace(self.capture, teams=(*self.capture.teams[:3], tied)), self.catalogue)
        for club in ("rival-1", "rival-3"):
            self.assertEqual((self.team(club, report).rank_lower, self.team(club, report).rank_upper), (1, 2))
        exact = replace(self.capture, teams=(self.capture.teams[0], strong, tied))
        report = build_league_report(exact, self.catalogue)
        for club in ("rival-1", "rival-3"):
            self.assertEqual((self.team(club, report).rank_lower, self.team(club, report).rank_upper), (1, 1))

    def test_unknown_positions_disable_team_score_but_keep_every_player_visible(self):
        document = self.capture.to_document()
        document["teams"][1]["positionsComplete"] = False
        document["teams"][1]["squad"]["players"][0]["positions"] = []
        report = build_league_report(type(self.capture).from_document(document), self.catalogue)
        team = self.team("rival-1", report)
        self.assertIsNone(team.score)
        players = rank_team_players(team, self.catalogue)
        self.assertEqual(len(players), 11)
        self.assertIsNone(players[-1].score)
        self.assertIsNone(players[-1].best_role)

    def test_player_filters_and_unknown_versus_uncaptured_gaps(self):
        team = self.team("rival-2")
        self.assertEqual(len(rank_team_players(team, self.catalogue, position="GK")), 1)
        self.assertEqual(len(rank_team_players(team, self.catalogue, role_key="generic")), 11)
        self.assertTrue(all(gap.supplied for _, gap in team_information_gaps(team)))
        document = self.capture.to_document()
        for player in document["teams"][2]["squad"]["players"]:
            del player["attributes"]["passing"]
        report = build_league_report(type(self.capture).from_document(document), self.catalogue)
        self.assertTrue(all(not gap.supplied for _, gap in team_information_gaps(self.team("rival-2", report))))
        self.assertEqual(self.team("rival-2", report).knowledge_counts, (0, 0, 0, 11))

    def test_unknown_rival_availability_is_explicit_and_does_not_override_owned_policy(self):
        rosters = tuple(replace(r, squad=replace(r.squad, players=tuple(replace(p, availability="unknown",
                      condition_percent=None) for p in r.squad.players))) for r in self.capture.teams)
        report = build_league_report(replace(self.capture, teams=rosters), self.catalogue)
        rival = self.team("rival-1", report)
        self.assertIsNotNone(rival.score)
        self.assertTrue(any("provisionally" in a for a in rival.assumptions))
        self.assertTrue(any("fallback" in a for a in rival.assumptions))
        self.assertEqual(rival.relative_to_us, "Not comparable")
        owned = self.team(rosters[0].squad.club.id, report)
        self.assertIsNone(owned.score)

    def test_narrower_knowledge_cannot_widen_the_team_score_band(self):
        roster = self.capture.teams[2]
        players = tuple(replace(p, attributes={"passing": AttributeObservation(Visibility.RANGE, minimum=8, maximum=14)})
                        for p in roster.squad.players)
        narrowed = replace(roster, squad=replace(roster.squad, players=players))
        report = build_league_report(replace(self.capture, teams=(*self.capture.teams[:2], narrowed, self.capture.teams[3])), self.catalogue)
        old, new = self.team("rival-2").score, self.team("rival-2", report).score
        self.assertGreaterEqual(new.lower, old.lower)
        self.assertLessEqual(new.upper, old.upper)


if __name__ == "__main__":
    unittest.main()

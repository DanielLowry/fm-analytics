"""The League page's hidden view: the capture, XI strength, results against strength, and the page.

A synthetic four-club league whose players are as good as their club's
number (Alpha 14, Bravo 12, us 10, Charlie 8), every one a natural in one
4-4-2 position, so the expected order is known by hand.
"""

import ast
import json
import math
import random
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.hidden_strength import (
    MIN_MODEL_MATCHES,
    build_hidden_strength,
    catalogue_shapes,
    closest_shapes,
    fit_strength_model,
    shape_label,
    shape_of,
)
from fm_analytics.domain.attributes import VISIBLE_ATTRIBUTES
from fm_analytics.domain.hidden import POSITION_CODES, HiddenCapture
from fm_analytics.domain.matches import Competition, MatchDetail, MatchRecord, PlayerMatchStats, TeamRef
from fm_analytics.match_ingest import record_capture_file
from fm_analytics.persistence.match_history import MatchHistory, MatchHistoryStore, MatchNote
from fm_analytics.hidden_reporting import build_hidden_strength_export, build_hidden_strength_report

from tests.match_support import VERTICAL_442_CODES
from tests.web_support import FIXTURE, WebServerHelpers

ROOT = Path(__file__).resolve().parent.parent
US, ALPHA, BRAVO, CHARLIE = (TeamRef("100", "Hungerford Town"), TeamRef("201", "Alpha"),
                             TeamRef("202", "Bravo"), TeamRef("203", "Charlie"))
QUALITY = {US.id: 10, ALPHA.id: 14, BRAVO.id: 12, CHARLIE.id: 8}
LEAGUE = Competition("148", "Test League South", "Test South")
SHAPE_442 = ("GK", "DL", "DC", "DC", "DR", "ML", "MC", "MC", "MR", "ST", "ST")


def player_document(club: TeamRef, index: int, position: str) -> dict:
    number = int(club.id) * 100 + index
    return {"id": str(10_000_000 + number), "shortId": number, "name": f"{club.name} {index}", "age": 25,
            "attributes": {name: QUALITY[club.id] for name in VISIBLE_ATTRIBUTES},
            "positionRatings": {code: 20 if code == position else 1 for code in POSITION_CODES}}


def capture_document() -> dict:
    teams, players = [], []
    for club in (US, ALPHA, BRAVO, CHARLIE):
        squad = [player_document(club, index, position) for index, position in enumerate(SHAPE_442 + ("MC",))]
        players += squad
        teams.append({"club": club.to_document(), "playerIds": [row["id"] for row in squad], "evidence": "test squad"})
    return {"format": "fm-analytics/hidden-attributes", "formatVersion": 1, "saveKey": "club:100",
            "gameDate": "2020-10-20", "season": "2020/21", "club": US.to_document(),
            "competition": {"id": "5123055", "name": LEAGUE.name, "shortName": LEAGUE.short_name},
            "teams": teams, "players": players, "notes": ["Read in 1.0 s."]}


def line_up(side: str, club: TeamRef, *, swap: bool = False, rename: bool = False) -> list[PlayerMatchStats]:
    """A club's first eleven as FM records them; `swap` starts its DC (3) in midfield and MC (6) at the back."""
    positions = list(SHAPE_442)
    if swap:
        positions[3], positions[6] = positions[6], positions[3]
    rows = []
    for index, position in enumerate(positions):
        number = int(club.id) * 100 + index
        name = f"{club.name} {index}" + (" Junior" if rename and index == 0 else "")
        rows.append(PlayerMatchStats(side, index, True, number, None, name, index + 1, VERTICAL_442_CODES[index], True,
                                     6.8, {}, position=position, start_position=position))
    return rows


def fixture_list() -> list[MatchRecord]:
    """Four double round-robins, 48 league matches; the stronger side usually wins."""
    clubs = (US, ALPHA, BRAVO, CHARLIE)
    matches, day = [], date(2020, 8, 1)
    for cycle in range(4):
        for home in clubs:
            for away in clubs:
                if home is away:
                    continue
                gap = QUALITY[home.id] - QUALITY[away.id]
                home_goals = max(0, gap // 2 + 1 + (cycle + len(matches)) % 2)
                away_goals = max(0, -gap // 2 + (len(matches) % 3 == 0))
                detail = MatchDetail({}, {}, tuple(line_up("home", home) + line_up("away", away)),
                                     formations={"home": "4-4-2", "away": "4-4-2"})
                matches.append(MatchRecord(day, LEAGUE, home, away, home_goals, away_goals, detail=detail, season=2020))
                day += timedelta(days=3)
    return matches


def world():
    capture = HiddenCapture.from_document(capture_document())
    matches = fixture_list()
    ours = [match for match in matches if US.id in (match.home.id, match.away.id)]
    theirs = [match for match in matches if US.id not in (match.home.id, match.away.id)]
    return capture, ours, theirs


def build(capture, ours, theirs, **options):
    keys = {match.key: "vertical_442" for match in ours}
    return build_hidden_strength(capture, ours, theirs, our_club_id=US.id, season=2020, our_tactic_keys=keys,
                                 catalogue=MVP_CATALOGUE, **options)


class CaptureTests(unittest.TestCase):
    def test_a_capture_round_trips_unchanged(self):
        capture = HiddenCapture.from_document(capture_document())
        again = HiddenCapture.from_document(json.loads(json.dumps(capture.to_document())))
        self.assertEqual(again, capture)
        self.assertEqual(again.content_hash(), capture.content_hash())
        self.assertEqual(len(capture.squad(ALPHA.id)), 12)
        self.assertEqual(capture.by_short_id(20_101).name, "Alpha 1")

    def test_positions_follow_our_squad_reads_rule(self):
        capture = HiddenCapture.from_document(capture_document())
        player = capture.players["10010000"]
        self.assertEqual(player.positions, ("GK",))
        ratings = dict(player.position_ratings, GK=9, DC=10, ST=14)
        self.assertEqual(replace(player, position_ratings=ratings).positions, ("DC", "ST"))
        lowly = {code: 3 for code in POSITION_CODES} | {"AMC": 8}
        self.assertEqual(replace(player, position_ratings=lowly).positions, ("AMC",))

    def test_a_malformed_capture_is_refused_with_the_reason(self):
        cases = {
            "not a version 1": lambda d: d.update(formatVersion=2),
            "unsupported fields": lambda d: d.update(currentAbility=1),
            "missing aerialReach": lambda d: d["players"][0]["attributes"].pop("aerialReach"),
            "unexpected currentAbility": lambda d: d["players"][0]["attributes"].update(currentAbility=12),
            "from 1 to 20": lambda d: d["players"][0]["attributes"].update(pace=21),
            "has no attributes": lambda d: d["teams"][1]["playerIds"].append("999"),
            "in two squads": lambda d: d["teams"][1]["playerIds"].append(d["teams"][0]["playerIds"][0]),
            "share FM's match ID": lambda d: d["players"][1].update(shortId=d["players"][0]["shortId"]),
            "our own club": lambda d: d["teams"].pop(0),
        }
        for message, change in cases.items():
            with self.subTest(message):
                document = capture_document()
                change(document)
                with self.assertRaisesRegex(ValueError, message):
                    HiddenCapture.from_document(document)


class ShapeTests(unittest.TestCase):
    def test_formations_are_named_by_line(self):
        self.assertEqual(shape_label(SHAPE_442), "4-4-2")
        self.assertEqual(shape_label(("GK", "DL", "DC", "DC", "DR", "DM", "ML", "MC", "MC", "MR", "ST")), "4-1-4-1")
        self.assertEqual(shape_label(("GK", "WBL", "DC", "DC", "DC", "WBR", "MC", "MC", "AMC", "ST", "ST")), "5-2-1-2")

    def test_a_shape_our_tactics_have_is_matched_exactly(self):
        matches = closest_shapes(shape_of(SHAPE_442), catalogue_shapes(MVP_CATALOGUE))
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0].exact)
        self.assertIn("vertical_442", matches[0].tactic_keys)

    def test_a_shape_we_lack_uses_the_nearest_moving_fewest_players_least(self):
        # FM's "4-3-3 Narrow": three strikers; our nearest is 4-3-1-2 with one striker dropping to AMC.
        narrow = shape_of(("GK", "DL", "DC", "DC", "DR", "MC", "MC", "MC", "ST", "ST", "ST"))
        matches = closest_shapes(narrow, catalogue_shapes(MVP_CATALOGUE))
        self.assertTrue(matches and not any(match.exact for match in matches))
        self.assertEqual({match.cost for match in matches}, {1})
        self.assertIn("positive_4312_narrow", {key for match in matches for key in match.tactic_keys})
        self.assertIn({"ST": frozenset({"AMC"})}, [dict(match.moves) for match in matches])


class ModelTests(unittest.TestCase):
    def test_the_fit_recovers_how_strength_turns_into_goals(self):
        generator = random.Random(3)

        def poisson(mean):
            limit, count, product = math.exp(-mean), 0, generator.random()
            while product > limit:
                count += 1
                product *= generator.random()
            return count

        samples = []
        for _ in range(4000):
            home, away = generator.uniform(38, 52), generator.uniform(38, 52)
            gap = home - away
            samples.append((home, away, poisson(math.exp(0.35 + 0.05 * gap)), poisson(math.exp(0.2 - 0.05 * gap))))
        model = fit_strength_model(samples)
        self.assertAlmostEqual(model.slope, 0.05, delta=3 * model.slope_error)
        self.assertLess(model.slope_error, 0.01)
        self.assertAlmostEqual(model.home_base, 0.35, delta=0.05)
        outcome = model.outcome(48, 44)
        self.assertAlmostEqual(outcome.home_win + outcome.draw + outcome.away_win, 1.0, places=9)
        self.assertGreater(outcome.expected_points("home"), model.outcome(44, 48).expected_points("home"))
        self.assertGreater(outcome.points_variance("away"), 0)

    def test_too_few_matches_give_no_model(self):
        self.assertIsNone(fit_strength_model([(45.0, 44.0, 1, 0)] * (MIN_MODEL_MATCHES - 1)))
        self.assertIsNone(fit_strength_model([(45.0, 44.0, 0, 0)] * MIN_MODEL_MATCHES))


class StrengthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture, cls.ours, cls.theirs = world()
        cls.report = build(cls.capture, cls.ours, cls.theirs)

    def test_every_league_match_is_scored_and_fitted(self):
        report = self.report
        self.assertEqual((report.league_matches, report.league_scored), (48, 48))
        self.assertIsNotNone(report.model)
        self.assertGreater(report.model.slope, 0)

    def test_better_players_mean_a_better_xi_in_our_tactic(self):
        scores = {row.club.name: row.xis["vertical_442"].score for row in self.report.by_tactic}
        self.assertGreater(scores["Alpha"], scores["Bravo"])
        self.assertGreater(scores["Bravo"], scores["Hungerford Town"])
        self.assertGreater(scores["Hungerford Town"], scores["Charlie"])
        self.assertEqual(self.report.our_tactics, (("vertical_442", 24),))
        self.assertTrue(next(row for row in self.report.by_tactic if row.club.id == US.id).ours)

    def test_our_matches_carry_both_xis_and_what_the_gap_predicts(self):
        rows = self.report.our_matches
        self.assertEqual(len(rows), 24)
        against_alpha = next(row for row in rows if row.opponent.id == ALPHA.id)
        against_charlie = next(row for row in rows if row.opponent.id == CHARLIE.id)
        self.assertLess(against_alpha.gap, 0)
        self.assertGreater(against_charlie.gap, 0)
        self.assertGreater(against_charlie.expected_points, against_alpha.expected_points)
        self.assertEqual(against_alpha.our_formation, "Vertical 4-4-2")
        self.assertEqual(against_alpha.their_formation, "4-4-2")
        self.assertEqual(len(against_alpha.ours.players), 11)

    def test_the_verdict_and_the_club_table_add_up(self):
        verdict, ours = self.report.verdict, next(row for row in self.report.clubs if row.ours)
        self.assertEqual((verdict.played, verdict.points), (ours.played, ours.points))
        self.assertAlmostEqual(verdict.expected_points, ours.expected_points)
        self.assertEqual(verdict.best_rank, 3)
        self.assertEqual(verdict.fielded_rank, 3)
        self.assertEqual(verdict.recent_played, 5)
        self.assertGreater(verdict.spread, verdict.recent_spread)
        self.assertAlmostEqual(sum(row.expected_points for row in self.report.clubs),
                               sum(row.points for row in self.report.clubs), delta=20)

    def test_formations_played_are_named_and_scored(self):
        rows = {row.club.id: row for row in self.report.by_formation}
        self.assertEqual([(use.name, use.matches, use.exact) for use in rows[ALPHA.id].formations], [("4-4-2", 24, True)])
        self.assertEqual(rows[US.id].formations[0].name, "Vertical 4-4-2")
        self.assertGreaterEqual(rows[ALPHA.id].best.score, next(
            row for row in self.report.by_tactic if row.club.id == ALPHA.id).xis["vertical_442"].score)

    def test_a_starter_stays_where_he_started(self):
        match = self.ours[0]
        side = match.side_of(US.id)
        players = tuple(p for p in match.detail.players if p.side != side) + tuple(line_up(side, US, swap=True))
        swapped = replace(match, detail=replace(match.detail, players=players))
        report = build(self.capture, [swapped], ())
        xi = report.our_matches[0].ours
        defender = next(player for player in xi.players if player.name == "Hungerford Town 3")
        self.assertEqual(defender.position, "MC")
        self.assertLess(xi.score, self.report.our_matches[0].ours.score)

    def test_a_starter_who_is_not_who_the_record_names_is_not_guessed(self):
        match = self.theirs[0]
        players = tuple(p for p in match.detail.players if p.side != "home") + tuple(
            line_up("home", match.home, rename=True))
        renamed = replace(match, detail=replace(match.detail, players=players))
        report = build(self.capture, self.ours, [renamed, *self.theirs[1:]])
        self.assertEqual((report.league_matches, report.league_scored), (48, 47))

    def test_a_squad_without_a_player_for_some_slot_plays_one_out_of_position(self):
        report = build(self.capture, self.ours, self.theirs, extra_tactic="balanced_433dm")
        self.assertEqual(report.compared_tactics, ("vertical_442", "balanced_433dm"))
        for row in report.by_tactic:
            xi = row.xis["balanced_433dm"]
            self.assertTrue(xi.out_of_position)
            self.assertIsNotNone(xi.score)


class ReportingTests(unittest.TestCase):
    def history(self, ours, notes=None):
        return MatchHistory("club:100", US, tuple(ours), (), notes or {}, {}, None)

    def test_the_report_infers_our_tactic_and_season_and_exports_with_its_warning(self):
        capture, ours, theirs = world()
        report = build_hidden_strength_report(capture, self.history(ours), theirs)
        self.assertEqual(report.season, 2020)
        self.assertEqual(report.our_tactics, (("vertical_442", 24),))
        document = build_hidden_strength_export(report)
        self.assertIn("hidden attributes", document["warning"])
        self.assertEqual(document["format"], "fm-analytics/hidden-strength")
        self.assertEqual(len(document["our_matches"]), 24)
        self.assertEqual(len(document["our_matches"][0]["our_line_up"]["players"]), 11)
        self.assertEqual(document["verdict"]["best_xi_rank"], 3)

    def test_a_noted_tactic_wins_over_the_inferred_one(self):
        capture, ours, theirs = world()
        notes = {ours[0].key: MatchNote(ours[0].key, "2026-10-11", "wing_play_442", None, "")}
        report = build_hidden_strength_report(capture, self.history(ours, notes), theirs)
        self.assertEqual(dict(report.our_tactics), {"vertical_442": 23, "wing_play_442": 1})

    def test_a_read_of_another_club_is_refused(self):
        capture, ours, theirs = world()
        with self.assertRaisesRegex(ValueError, "match history of Alpha"):
            build_hidden_strength_report(capture, MatchHistory("club:201", ALPHA, (), (), {}, {}, None), theirs)


class BoundaryTests(unittest.TestCase):
    """Hidden values reach only the hidden view: nothing else may import them."""

    HIDDEN = {"fm_analytics.domain.hidden", "fm_analytics.analytics.hidden_strength", "fm_analytics.hidden_export",
              "fm_analytics.hidden_reporting", "fm_analytics.web.hidden_state", "fm_analytics.web.hidden_render",
              "fm_analytics.web.hidden_pages"}
    # The hidden modules themselves, and the web plumbing that routes to them.
    ALLOWED = {"domain/hidden.py", "analytics/hidden_strength.py", "hidden_export.py", "hidden_reporting.py",
               "web/hidden_state.py", "web/hidden_render.py", "web/hidden_pages.py",
               "web/handlers.py", "web/server.py", "web/server_args.py"}

    def test_only_the_hidden_view_imports_hidden_data(self):
        source = ROOT / "src" / "fm_analytics"
        offenders = []
        for path in source.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            names |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            if names & self.HIDDEN and path.relative_to(source).as_posix() not in self.ALLOWED:
                offenders.append(path.relative_to(source).as_posix())
        self.assertEqual(offenders, [])

    def test_the_recommendation_path_never_imports_hidden_data(self):
        import subprocess
        import sys
        code = ("import sys, fm_analytics.reporting, fm_analytics.cli; "
                "print(sorted(name for name in sys.modules if 'hidden' in name))")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "[]")


class PageTests(WebServerHelpers, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.store = MatchHistoryStore(self.directory / "history.sqlite3")
        self.hidden = self.directory / "hidden.json"
        self.captures = []

    def record_matches(self):
        _capture, ours, theirs = world()
        document = {"format": "fm-analytics/match-capture", "formatVersion": 1, "capturedAt": "2026-10-11T10:00:00+00:00",
                    "gameDate": "2020-10-20", "source": {"tool": "tests", "managedClub": US.to_document()},
                    "matches": [match.to_document() for match in ours], "competitionResults": [],
                    "clubMatches": [match.to_document() for match in theirs]}
        path = self.directory / "capture.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        record_capture_file(self.store, path)

    def serve(self):
        from fm_analytics.web.hidden_state import hidden_json_provider

        def capture():
            self.captures.append(True)
            self.hidden.write_text(json.dumps(capture_document()), encoding="utf-8")
            return "Read 48 players at 4 clubs from FM at game date 2020-10-20."

        return self._serve(FIXTURE, match_store=self.store, hidden_provider=hidden_json_provider(self.hidden),
                           hidden_capture=capture)

    def get_ready(self, port, path="/league/hidden"):
        for _ in range(200):
            status, body = self._get(port, path)
            if status != 202:
                return status, body
            time.sleep(0.05)
        self.fail("the hidden view never finished")

    def test_before_a_read_the_page_offers_one_and_says_what_it_is(self):
        status, body = self._get(self.serve(), "/league/hidden")
        self.assertEqual(status, 200)
        self.assertIn("This page uses hidden attributes", body)
        self.assertIn("Read hidden attributes from FM", body)
        self.assertIn('href="/league" class="active"', body)

    def test_reading_from_fm_then_the_tables(self):
        self.record_matches()
        port = self.serve()
        status, location, _body = self._post(port, "/league/hidden/capture")
        self.assertEqual((status, location, self.captures), (303, "/league/hidden", [True]))
        status, body = self._get(port, "/league/hidden")
        self.assertEqual(status, 202)
        self.assertIn("data-league-pending", body)
        status, body = self.get_ready(port)
        self.assertEqual(status, 200)
        self.assertIn("This page uses hidden attributes", body)
        for heading in ("1 · The XIs in our matches", "2 · Best XI in our tactics",
                        "3 · Best XI in the formations they've played", "4 · Results against strength"):
            self.assertIn(heading, body)
        self.assertEqual(body.count("data-copy-markdown"), 4)
        self.assertIn("Copy everything as JSON", body)
        self.assertIn("Read 48 players at 4 clubs", body)

    def test_choices_are_checked(self):
        port = self.serve()
        self.assertEqual(self._get(port, "/league/hidden?tactic=nope")[0], 400)
        self.assertEqual(self._get(port, "/league/hidden?season=x")[0], 400)

    def test_the_league_page_links_to_it(self):
        from fm_analytics.web.league_pages import _HIDDEN_LINK
        self.assertIn("/league/hidden", _HIDDEN_LINK)
        self.assertIn("cannot see", _HIDDEN_LINK)


if __name__ == "__main__":
    unittest.main()

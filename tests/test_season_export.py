import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from fm_analytics import match_ingest
from fm_analytics.analytics.match_analysis import ReviewFilters
from fm_analytics.analytics.match_players import summarise_players
from fm_analytics.cli import load_fixture
from fm_analytics.domain.matches import MatchCapture
from fm_analytics.match_ingest import main, record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import (
    RecommendationPolicy, build_match_export, build_match_report, build_match_review, build_matches_export,
    build_recommendation_bundle, build_season_export,
)

from tests.match_support import capture_document, lineup, player, season, two_seasons
from tests.test_match_history import intervention
from tests.web_support import WebServerHelpers, write_complete_fixture

DETAILED = "2019-09-01:100:201"
GENERATED = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class HistoryCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.db = self.directory / "history.sqlite3"
        self.capture = self.directory / "capture.json"
        self.capture.write_text(json.dumps(capture_document(season())), encoding="utf-8")
        self.store = MatchHistoryStore(self.db)
        record_capture_file(self.store, self.capture)
        self.history = self.store.load_history("club:100")

    def bundle(self, pinned=()):
        game, squad = load_fixture(write_complete_fixture(self.directory))
        return build_recommendation_bundle(game, squad, policy=RecommendationPolicy(pinned_tactics=pinned))

    def export(self, detail, **kwargs):
        return build_season_export(self.history, detail=detail, generated_at=GENERATED, **kwargs)

    def detailed(self, document):
        return next(match for match in document["matches"] if match["key"] == DETAILED)


class DetailLevelTests(HistoryCase):
    def test_every_level_has_the_same_sections_and_is_plain_json(self) -> None:
        for detail in ("basic", "standard", "verbose"):
            document = self.export(detail)
            self.assertEqual(
                list(document),
                ["format", "formatVersion", "meta", "season", "review", "diagnostics", "goals", "roles", "players", "matches"],
            )
            self.assertEqual(document["formatVersion"], 2)
            self.assertIn("top_opportunities", document["diagnostics"])
            self.assertIsNone(document["diagnostics"]["active_intervention"])
            self.assertEqual(document["diagnostics"]["intervention_history"], [])
            self.assertEqual(document["meta"]["detail"], detail)
            self.assertEqual(json.loads(json.dumps(document)), document)

    def test_the_review_is_the_shared_computation(self) -> None:
        document = self.export("basic")
        review = build_match_review(self.history, filters=ReviewFilters(competitions="competitive"))
        overall = document["review"]["overall"]
        self.assertEqual((overall["played"], overall["won"], overall["drawn"], overall["lost"]),
                         (review.overall.matches, review.overall.wins, review.overall.draws, review.overall.losses))
        self.assertEqual(document["season"]["competitive"]["played"], 5)  # the friendly is left out
        self.assertEqual(document["season"]["friendlies"]["played"], 1)
        self.assertEqual(document["season"]["cups"]["played"], 1)
        self.assertEqual(len(document["matches"]), 6)  # but listed

    def test_an_active_intervention_and_its_frozen_baseline_are_exported(self) -> None:
        started = self.store.start_intervention("club:100", intervention())
        self.history = self.store.load_history("club:100")
        diagnostics = self.export("basic")["diagnostics"]
        active = diagnostics["active_intervention"]
        self.assertEqual((active["id"], active["finding_key"]), (started.id, "finishing_recent"))
        self.assertEqual(active["baseline"]["conversion_pct"], 8.0)
        self.assertEqual(active["evaluation"]["status"], "collecting")
        self.assertEqual(len(diagnostics["intervention_history"]), 1)

    def test_the_league_table_is_rebuilt_as_of_the_last_capture(self) -> None:
        season = self.export("basic")["season"]
        us = next(row for row in season["league_table_now"] if row["us"])
        self.assertEqual((us["played"], us["points"]), (4, 5))
        self.assertEqual(season["league_position_now"], us["pos"])
        self.assertEqual([step["position_after"] for step in season["league_position_trajectory"]][-1], us["pos"])
        self.assertEqual(season["league_form_last6"], "DLDW")

    def test_the_table_now_is_this_seasons_and_the_trajectory_starts_again_each_season(self) -> None:
        matches, results = two_seasons()
        self.capture.write_text(json.dumps(capture_document(matches, game_date="2020-08-09", league_results=results)),
                                encoding="utf-8")
        record_capture_file(self.store, self.capture)
        self.history = self.store.load_history("club:100")
        season = self.export("basic")["season"]
        self.assertEqual(season["league_season"], 2020)
        self.assertEqual({row["team"] for row in season["league_table_now"]}, {"Hungerford Town", "Alpha", "Bravo", "Delta"})
        us = next(row for row in season["league_table_now"] if row["us"])
        self.assertEqual((us["played"], us["points"]), (2, 3))
        steps = [(step["season"], step["points_after"]) for step in season["league_position_trajectory"]]
        self.assertEqual(steps, [(2019, 1), (2019, 1), (2019, 2), (2019, 5), (2020, 0), (2020, 3)])

    def test_basic_has_one_line_per_match_and_per_player(self) -> None:
        document = self.export("basic")
        match = self.detailed(document)
        self.assertEqual((match["result"], match["score"], match["tactic"]), ("W", "2-1", "Vertical 4-4-2"))
        self.assertNotIn("our_players", match)
        self.assertNotIn("per90", document["players"][0])

    def test_standard_adds_line_ups_panel_summaries_and_per_90s(self) -> None:
        document = self.export("standard")
        match = self.detailed(document)
        self.assertEqual(match["summary_for"]["possession"], 40)
        self.assertEqual(len(match["our_players"]), 11)
        self.assertNotIn("stats", match["our_players"][0])
        self.assertNotIn("their_players", match)
        scorer = next(player for player in document["players"] if player["name"] == "Home 11")
        self.assertEqual((scorer["goals"], scorer["shots"], scorer["per90"]["shots"]), (1, 5, 5.0))

    def test_verbose_adds_every_stat_line_both_panels_and_the_timeline(self) -> None:
        match = self.detailed(self.export("verbose"))
        self.assertEqual(match["team_stats_for"]["corners"], 3)
        self.assertEqual(len(match["their_players"]), 11)
        self.assertEqual(match["our_players"][10]["stats"], {"shots": 5, "goals": 1, "clear_cut_chances": 2})
        self.assertEqual([event["minute"] for event in match["timeline"] if event["event"] == "goal"], [12, 50, 93])

    def test_line_ups_show_where_each_player_played_and_verbose_where_he_started(self) -> None:
        self.assertIsNone(self.detailed(self.export("standard"))["our_players"][10]["position"])
        matches = season()
        striker = matches[-1]["detail"]["players"][10]
        striker.update({"position": "ST", "startPosition": "ST", "startCentreSide": "left"})
        self.capture.write_text(json.dumps(capture_document(matches)), encoding="utf-8")
        record_capture_file(self.store, self.capture)
        self.history = self.store.load_history("club:100")
        standard = self.detailed(self.export("standard"))["our_players"][10]
        self.assertEqual(standard["position"], "ST")
        self.assertNotIn("start_position", standard)
        verbose = self.detailed(self.export("verbose"))["our_players"][10]
        self.assertEqual((verbose["start_position"], verbose["start_centre_side"]), ("ST", "left"))

    def test_a_cup_tie_after_extra_time_and_penalties_reads_from_our_side(self) -> None:
        matches = season()
        cup = next(match for match in matches if match["competition"]["name"] == "Test Cup")
        # We were away: 1-1 after 90 and after extra time, and won 5-4 on penalties.
        cup.update({"homeGoals": 1, "awayGoals": 1, "scoreAt90": [1, 1], "penalties": [4, 5]})
        self.capture.write_text(json.dumps(capture_document(matches)), encoding="utf-8")
        record_capture_file(self.store, self.capture)
        self.history = self.store.load_history("club:100")
        document = self.export("basic")
        row = next(match for match in document["matches"] if match["type"] == "cup")
        self.assertEqual((row["score"], row["result"]), ("1-1", "D"))  # a shootout is not a win
        self.assertEqual((row["after_extra_time"], row["score_at_90"], row["penalties"]), (True, "1-1", "5-4"))
        self.assertTrue(any("after extra time" in caveat for caveat in document["meta"]["caveats"]))
        league = self.detailed(document)
        self.assertNotIn("after_extra_time", league)

    def test_every_level_lists_each_matchs_goals_and_red_cards_from_our_side(self) -> None:
        matches = season()
        matches[-1]["incidents"] = [
            {"minute": 12, "side": "home", "kind": "goal", "playerShortId": 1, "player": "Home 10"},
            {"minute": 50, "side": "away", "kind": "penalty", "playerShortId": 2, "player": "Away 11"},
            {"minute": 70, "side": "away", "kind": "sent_off", "playerShortId": 3, "player": "Away 4"},
            {"minute": 90, "addedTime": 3, "side": "home", "kind": "own_goal", "playerShortId": 4, "player": "Away 2"},
        ]
        self.capture.write_text(json.dumps(capture_document(matches)), encoding="utf-8")
        record_capture_file(self.store, self.capture)
        self.history = self.store.load_history("club:100")
        document = self.export("basic")
        match = self.detailed(document)
        self.assertEqual(match["goals"], [
            {"minute": "12", "team": "us", "scorer": "Home 10"},
            {"minute": "50", "team": "them", "scorer": "Away 11", "penalty": True},
            {"minute": "90+3", "team": "us", "scorer": "Away 2", "own_goal": True},
        ])
        self.assertEqual(match["sent_off"], [{"minute": "70", "team": "them", "player": "Away 4"}])
        goals = document["goals"]
        self.assertEqual((goals["penalties"], goals["own_goals"], goals["sent_off"]),
                         ({"for": 0, "against": 1}, {"for": 1, "against": 0}, {"ours": 0, "theirs": 1}))

    def test_an_unknown_level_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "basic, standard, verbose"):
            self.export("everything")


class SquadSectionTests(HistoryCase):
    def test_without_a_squad_the_document_says_why(self) -> None:
        document = self.export("standard", squad_note="left out (--squad none)")
        self.assertNotIn("squad", document)
        self.assertEqual(document["meta"]["squad"], "left out (--squad none)")

    def test_standard_has_the_squad_and_the_top_of_the_ranking_plus_pins(self) -> None:
        bundle = self.bundle(pinned=(bundle_last := self.bundle().recommendation.evaluations[-1].tactic.key,))
        document = self.export("standard", bundle=bundle)
        self.assertEqual(len(document["squad"]), 11)
        self.assertNotIn("attributes", document["squad"][0])
        ranking = document["recommendation"]["tactic_ranking"]
        self.assertEqual([row["rank"] for row in ranking][:10], list(range(1, 11)))
        self.assertEqual(ranking[-1]["tactic_key"], bundle_last)
        primary = document["recommendation"]["primary"]
        self.assertEqual(primary["tactic_key"], bundle_last)  # the first pin is the primary, not the top
        self.assertEqual(len(primary["xi"]), len(bundle.primary.assignments))
        self.assertEqual(
            primary["bench_coverage"]["credible_cover_ratio"],
            bundle.bench.credible_cover_ratio,
        )
        self.assertEqual(
            primary["bench_coverage"]["below_threshold"],
            list(bundle.bench.weakly_covered_slots),
        )
        self.assertEqual(document["meta"]["squad"], f"read at game date {bundle.game.game_date.isoformat()}")

    def test_verbose_has_every_attribute_and_the_whole_ranking(self) -> None:
        bundle = self.bundle()
        document = self.export("verbose", bundle=bundle)
        self.assertEqual(document["squad"][0]["attributes"]["passing"], 10)
        self.assertEqual(len(document["recommendation"]["tactic_ranking"]), len(bundle.recommendation.evaluations))
        self.assertIn("recruitment_briefs", document["recommendation"])

    def test_basic_never_carries_the_squad(self) -> None:
        document = self.export("basic", bundle=self.bundle())
        self.assertNotIn("squad", document)
        self.assertEqual(document["meta"]["squad"], "left out (basic)")


class MatchExportTests(HistoryCase):
    def document(self, key=DETAILED):
        return build_match_export(self.history, build_match_report(self.history, key), generated_at=GENERATED)

    def test_a_match_is_its_verbose_season_entry_with_their_full_lines_and_more(self) -> None:
        document = self.document()
        self.assertEqual((document["format"], document["formatVersion"]), ("fm-analytics/match-export", 1))
        self.assertEqual(json.loads(json.dumps(document)), document)
        match, entry = document["match"], self.detailed(self.export("verbose"))
        self.assertEqual({key: match[key] for key in entry if key != "their_players"},
                         {key: value for key, value in entry.items() if key != "their_players"})
        self.assertEqual([line["name"] for line in match["their_players"]],
                         [line["name"] for line in entry["their_players"]])
        self.assertNotIn("stats", entry["their_players"][0])  # the season keeps theirs short
        self.assertIn("stats", match["their_players"][0])
        self.assertEqual(match["league_at_kickoff"], {
            "league": "Test League South", "season": None, "teams": 4,
            "us": {"position": 4, "played": 3, "points": 2}, "them": {"position": 1, "played": 3, "points": 7},
        })
        self.assertEqual(match["unused_substitutes"], {"us": [], "them": []})
        self.assertEqual(match["fm_saved_tactics"], {})
        self.assertIsNone(match["your_pre_match_rating"])

    def test_a_result_only_match_says_so_and_keeps_its_context(self) -> None:
        document = self.document("2019-08-10:202:100")
        match = document["match"]
        self.assertFalse(match["full_stats"])
        self.assertEqual((match["score"], match["attendance"]), ("0-2", 500))
        self.assertNotIn("fm_saved_tactics", match)
        self.assertTrue(any("Only the result was found" in caveat for caveat in document["meta"]["caveats"]))

    def test_your_rating_the_unused_substitutes_and_the_saved_tactics_are_included(self) -> None:
        matches = season()
        detail = matches[-1]["detail"]
        detail["players"].append(player("home", 11, 0, name="Home 12") | {"played": False, "rating": None})
        detail["savedTactics"] = {"home": {"name": "My 4-4-2", "slots": [
            {"position": "GK", "centreSide": None, "roleCode": 1, "dutyCode": 0x200000},
            {"position": "DC", "centreSide": "left", "roleCode": 2, "dutyCode": 0x4000000},
        ]}}
        self.capture.write_text(json.dumps(capture_document(matches)), encoding="utf-8")
        record_capture_file(self.store, self.capture)
        self.store.add_note("club:100", DETAILED, tactic_key=None, opponent_rating=1, note="Sat deep")
        self.history = self.store.load_history("club:100")
        document = self.document()
        match = document["match"]
        self.assertEqual((match["your_pre_match_rating"], match["note"]), (1, "Sat deep"))
        self.assertEqual(match["unused_substitutes"], {"us": ["Home 12"], "them": []})
        tactic = match["fm_saved_tactics"]["us"]
        self.assertEqual(tactic["name"], "My 4-4-2")
        self.assertEqual([(slot["position"], slot["centre_side"], slot["duty"]) for slot in tactic["slots"]],
                         [("GK", None, "defend"), ("DC", "left", None)])
        caveats = " ".join(document["meta"]["caveats"])
        self.assertIn("your_pre_match_rating is how strong you judged them", caveats)
        self.assertIn("duty of null", caveats)


class MatchesExportTests(HistoryCase):
    """The Matches page's "Copy all match data": every selected match, each as its own page copies it."""

    def use_two_seasons(self) -> None:
        matches, results = two_seasons()
        self.capture.write_text(json.dumps(
            capture_document(matches, game_date="2020-08-09", league_results=results)
        ), encoding="utf-8")
        record_capture_file(self.store, self.capture)
        self.history = self.store.load_history("club:100")

    def test_each_match_is_what_its_own_page_copies(self) -> None:
        document = build_matches_export(self.history, filters=ReviewFilters(competitions="all"), generated_at=GENERATED)
        self.assertEqual((document["format"], document["formatVersion"]), ("fm-analytics/matches-export", 1))
        self.assertEqual(json.loads(json.dumps(document)), document)
        self.assertEqual(len(document["matches"]), 6)
        for entry in document["matches"]:
            self.assertEqual(entry, build_match_export(self.history, build_match_report(self.history, entry["key"]))["match"])
        self.assertEqual(document["meta"]["generated_at"], "2026-09-29T12:00:00+00:00")
        self.assertIn("5 match(es) have the result only", " ".join(document["meta"]["caveats"]))

    def test_it_holds_only_the_selection_with_the_pages_own_figures(self) -> None:
        self.use_two_seasons()
        filters = ReviewFilters(competitions="league", venue="home", season=2019)
        document = build_matches_export(self.history, filters=filters, generated_at=GENERATED)
        review = build_match_review(self.history, filters=filters)
        self.assertEqual([entry["key"] for entry in document["matches"]], [s.match.key for s in review.matches])
        self.assertEqual([entry["date"] for entry in document["matches"]], ["2019-08-03", "2019-09-01"])
        self.assertEqual(document["selection"], {
            "season": "2019/20", "competitions": "League only", "venue": "Home", "tactic": "Any tactic",
            "opponents_grouped_by": review.grouping_label, "matches": 2, "with_full_stats": 1,
        })
        overall = document["review"]["overall"]
        self.assertEqual((overall["played"], overall["won"], overall["drawn"]), (2, 1, 1))
        self.assertEqual(len(document["review"]["by_opponent"]), len(review.groups))
        self.assertEqual([player["name"] for player in document["players"]], [p.name for p in review.players])
        self.assertIn("FM files no season for a friendly", " ".join(document["meta"]["caveats"]))


class PlayerSeasonTests(unittest.TestCase):
    def test_players_are_summed_across_matches_with_starts_subs_and_ratings_in_order(self) -> None:
        first = MatchCapture.from_document(capture_document(season())).matches[-1]
        striker = first.detail.players_for("home")[10]
        role = "Advanced Forward (Attack)"
        appearances = [(striker, date(2019, 9, 8), "Bravo", role), (striker, date(2019, 9, 1), "Alpha", role)]
        (row,) = summarise_players(appearances)
        self.assertEqual((row.appearances, row.starts, row.minutes, row.stat("goals")), (2, 2, 180, 2))
        self.assertEqual([item.opponent for item in row.ratings], ["Alpha", "Bravo"])
        self.assertEqual(row.roles, (("Advanced Forward (Attack)", 2),))
        self.assertEqual(row.per_90(row.stat("shots")), 5.0)


class ExportCliTests(HistoryCase):
    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--db", str(self.db), "export", *map(str, args)])
        return code, output.getvalue()

    def test_basic_writes_a_file_and_never_reads_fm(self) -> None:
        path = self.directory / "out.json"
        with mock.patch.object(match_ingest, "read_live_bundle") as live:
            code, text = self.run_cli("--detail", "basic", "--output", path)
        self.assertEqual(code, 0, text)
        live.assert_not_called()
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["meta"]["detail"], "basic")
        self.assertIn(f"Wrote {path} (basic, 6 matches", text)

    def test_standard_reads_the_squad_with_the_pinned_tactics(self) -> None:
        bundle = self.bundle(pinned=("vertical_442",))
        with mock.patch.object(match_ingest, "read_live_bundle", return_value=bundle) as live:
            code, text = self.run_cli("--my-tactics", "vertical_442", "--output", "-")
        self.assertEqual(code, 0, text)
        live.assert_called_once()
        pinned, history = live.call_args.args
        self.assertEqual((pinned, history.club.id), (("vertical_442",), "100"))  # form comes from this history
        self.assertEqual(len(json.loads(text)["squad"]), 11)
        instructions = json.loads(text)["recommendation"]["primary"]["instructions"]
        self.assertIn("Counter", instructions)
        self.assertIn("Regroup", instructions)
        self.assertIn("Standard Line of Engagement", instructions)
        self.assertIn("Standard Defensive Line", instructions)

    def test_squad_none_skips_fm_and_a_failed_read_says_how_to_skip_it(self) -> None:
        with mock.patch.object(match_ingest, "read_live_bundle") as live:
            code, text = self.run_cli("--squad", "none", "--output", "-")
        self.assertEqual(code, 0)
        live.assert_not_called()
        self.assertEqual(json.loads(text)["meta"]["squad"], "left out (--squad none)")
        with mock.patch.object(match_ingest.LinuxProtonDataSource, "read_snapshot",
                               side_effect=RuntimeError("FM20 is not running")):
            code, text = self.run_cli("--output", "-")
        self.assertEqual(code, 1)
        self.assertIn("use --squad none", text)

    def test_the_default_file_is_named_for_the_club_date_and_level(self) -> None:
        path = match_ingest.export_path("Hampton & Richmond Borough", "2019-11-16", "verbose")
        self.assertEqual(path.name, "hampton-richmond-borough-2019-11-16-verbose.json")


class ExportApiTests(WebServerHelpers, HistoryCase):
    def serve(self) -> int:
        return self._serve(write_complete_fixture(self.directory), match_store=self.store)

    def test_the_api_serves_the_same_document_as_the_shared_computation(self) -> None:
        status, body = self._get(self.serve(), "/api/export?detail=basic")
        self.assertEqual(status, 200)
        document = json.loads(body)
        expected = self.export("basic")
        document["meta"].pop("generated_at")
        expected["meta"].pop("generated_at")
        self.assertEqual(document, expected)

    def test_standard_includes_the_servers_squad_unless_asked_not_to(self) -> None:
        port = self.serve()
        _status, body = self._get(port, "/api/export")
        self.assertEqual(len(json.loads(body)["squad"]), 11)
        _status, body = self._get(port, "/api/export?squad=none")
        self.assertNotIn("squad", json.loads(body))

    def test_the_matches_export_takes_the_pages_filters(self) -> None:
        status, body = self._get(self.serve(), "/api/matches-export?competitions=league&venue=away")
        self.assertEqual(status, 200)
        document = json.loads(body)
        expected = build_matches_export(self.history, filters=ReviewFilters(competitions="league", venue="away"))
        document["meta"].pop("generated_at")
        expected["meta"].pop("generated_at")
        self.assertEqual(document, expected)
        self.assertEqual(len(document["matches"]), 2)

    def test_the_matches_export_refuses_bad_filters_and_an_empty_history(self) -> None:
        status, body = self._get(self.serve(), "/api/matches-export?season=last")
        self.assertEqual(status, 400)
        self.assertIn("season must be a number", json.loads(body)["error"])
        empty = self._serve(write_complete_fixture(self.directory),
                            match_store=MatchHistoryStore(self.directory / "empty.sqlite3"))
        status, body = self._get(empty, "/api/matches-export")
        self.assertEqual(status, 404)
        self.assertIn("No matches", json.loads(body)["error"])

    def test_bad_parameters_and_an_empty_history_are_json_errors(self) -> None:
        port = self.serve()
        status, body = self._get(port, "/api/export?detail=everything")
        self.assertEqual(status, 400)
        self.assertIn("basic, standard, verbose", json.loads(body)["error"])
        empty = self._serve(write_complete_fixture(self.directory),
                            match_store=MatchHistoryStore(self.directory / "empty.sqlite3"))
        status, body = self._get(empty, "/api/export")
        self.assertEqual(status, 404)
        self.assertIn("No matches", json.loads(body)["error"])

    def test_the_matches_page_links_to_each_level(self) -> None:
        _status, body = self._get(self.serve(), "/matches")
        for level in ("basic", "standard", "verbose"):
            self.assertIn(f"/api/export?detail={level}", body)


if __name__ == "__main__":
    unittest.main()

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
from fm_analytics.analytics.match_roles import RoleCodes
from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.cli import load_fixture
from fm_analytics.domain.matches import MatchCapture
from fm_analytics.match_ingest import main, record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import RecommendationPolicy, build_match_review, build_recommendation_bundle, build_season_export

from tests.match_support import capture_document, lineup, season
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
                ["format", "formatVersion", "meta", "season", "review", "goals", "roles", "players", "matches"],
            )
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

    def test_the_league_table_is_rebuilt_as_of_the_last_capture(self) -> None:
        season = self.export("basic")["season"]
        us = next(row for row in season["league_table_now"] if row["us"])
        self.assertEqual((us["played"], us["points"]), (4, 5))
        self.assertEqual(season["league_position_now"], us["pos"])
        self.assertEqual([step["position_after"] for step in season["league_position_trajectory"]][-1], us["pos"])
        self.assertEqual(season["league_form_last6"], "DLDW")

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


class PlayerSeasonTests(unittest.TestCase):
    def test_players_are_summed_across_matches_with_starts_subs_and_ratings_in_order(self) -> None:
        first = MatchCapture.from_document(capture_document(season())).matches[-1]
        codes = RoleCodes.build(MVP_CATALOGUE)
        striker = first.detail.players_for("home")[10]
        appearances = [(striker, date(2019, 9, 8), "Bravo"), (striker, date(2019, 9, 1), "Alpha")]
        (row,) = summarise_players(appearances, codes)
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
        live.assert_called_once_with(("vertical_442",))
        self.assertEqual(len(json.loads(text)["squad"]), 11)

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

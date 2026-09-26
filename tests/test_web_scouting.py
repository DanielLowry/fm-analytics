import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes
from fm_analytics.analytics import ScoutingCandidate
from fm_analytics.web.rendering import (
    ScoutingPoolNotBuilt,
    _scouting_refresh_command,
)
from tests.web_support import FIXTURE, WebServerHelpers, write_complete_fixture


class ScoutingPageTests(WebServerHelpers, unittest.TestCase):
    def test_scouting_page_makes_unknown_profiles_a_reason_to_scout(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-1", name="Unknown Striker", positions=("ST",),
                    attributes={}, age=19, club="Example FC", footedness="Right",
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        status, body = self._get(port, "/scouting?role=af_attack&position=ST")

        self.assertEqual(status, 200)
        self.assertIn("Unknown Striker", body)
        self.assertIn("Scout first", body)
        self.assertIn("floor / estimate / ceiling", body)

    def test_scouting_page_has_a_name_box_and_a_live_results_container(self) -> None:
        """The as-you-type behaviour depends on this exact id and input name."""
        port = self._serve(FIXTURE)
        status, body = self._get(port, "/scouting")

        self.assertEqual(status, 200)
        self.assertIn("name='name'", body)
        self.assertIn("name='tactic'", body)
        self.assertIn("Generic position / role ranking", body)
        self.assertIn("id='scouting-results'", body)
        self.assertIn("fetch(", body)

    def test_scouting_can_rank_targets_by_gain_for_a_selected_tactic(self) -> None:
        required = required_role_attributes()

        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="strong-target",
                    name="Strong Target",
                    positions=("ST",),
                    attributes={
                        name: AttributeObservation(Visibility.KNOWN, value=20)
                        for name in required
                    },
                    age=22,
                    scouting_knowledge=100,
                ),
            )

        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path, scouting_provider)

            status, body = self._get(port, "/scouting?tactic=balanced_442")
            player_status, player_body = self._get(
                port,
                "/scouting/player/strong-target?tactic=balanced_442",
            )

        self.assertEqual(status, 200)
        self.assertIn("Impact on Balanced 4-4-2", body)
        self.assertIn("Strong Target", body)
        self.assertIn("Current score:", body)
        self.assertIn("XI gain", body)
        self.assertIn("Starts", body)
        self.assertIn("Sorted by <b>XI gain (estimate)</b>", body)
        self.assertEqual(player_status, 200)
        self.assertIn("Tactic impact", player_body)
        self.assertIn("name='tactic'", player_body)
        self.assertIn("Impact on Balanced 4-4-2", player_body)
        self.assertIn("Projected tactic score", player_body)
        self.assertIn("XI gain", player_body)
        self.assertIn("Starts", player_body)

    def test_scouting_results_fragment_matches_the_full_page_for_the_same_filters(self) -> None:
        """The live-filter endpoint must compute the same thing the full page does."""
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-1", name="Ashley Wells", positions=(), raw_positions=("DR",),
                    attributes={}, age=19, club="Example FC", footedness="Right",
                ),
                ScoutingCandidate(
                    id="external-2", name="Someone Else", positions=(), raw_positions=("DR",),
                    attributes={}, age=19, club="Example FC", footedness="Right",
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        full_status, full_body = self._get(
            port, "/scouting?position=DR&includeRawPositions=1&name=Wells"
        )
        fragment_status, fragment_body = self._get(
            port, "/scouting/results?position=DR&includeRawPositions=1&name=Wells"
        )

        self.assertEqual(full_status, 200)
        self.assertEqual(fragment_status, 200)
        self.assertIn("Ashley Wells", full_body)
        self.assertNotIn("Someone Else", full_body)
        self.assertIn("Ashley Wells", fragment_body)
        self.assertNotIn("Someone Else", fragment_body)
        # The fragment is only the results half -- no filter form, no page shell.
        self.assertNotIn("Find a target", fragment_body)
        self.assertNotIn("<!doctype html>", fragment_body)

    def test_scouting_results_fragment_reports_errors_without_the_page_shell(self) -> None:
        def scouting_provider():
            raise OSError("scouting capture is unreadable")

        port = self._serve(FIXTURE, scouting_provider)
        status, body = self._get(port, "/scouting/results")

        self.assertEqual(status, 503)
        self.assertIn("scouting capture is unreadable", body)

    def test_a_position_with_no_role_is_ranked_with_min_median_and_max(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-1", name="Ranked Defender", positions=("DC",),
                    attributes={}, age=20, club="Example FC", scouting_knowledge=9,
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        status, body = self._get(port, "/scouting?view=scouted&position=DC")

        self.assertEqual(status, 200)
        self.assertIn("Ranked for DC (1)", body)
        self.assertIn("data-sort='median'", body)
        self.assertIn("Sorted by <b>Median (best guess)</b>", body)
        self.assertIn("Ranked Defender", body)

    def test_the_scouted_tab_ranks_everyone_without_choosing_a_position_first(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="a", name="Scouted One", positions=(), attributes={},
                    age=20, scouting_knowledge=9,
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, body = self._get(port, "/scouting?view=scouted")

        self.assertIn("Ranked, all positions (1)", body)
        self.assertIn("data-sort='median'", body)
        self.assertIn("data-sort='minimum'", body)
        self.assertIn("data-sort='ceiling'", body)

    def test_column_headings_sort_on_the_server_and_show_the_direction(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(id="a", name="Older", positions=(), attributes={}, age=30, scouting_knowledge=9),
                ScoutingCandidate(id="b", name="Younger", positions=(), attributes={}, age=18, scouting_knowledge=9),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, ascending = self._get(port, "/scouting?view=scouted&sort=age")
        _status, descending = self._get(port, "/scouting?view=scouted&sort=age&dir=desc")

        self.assertIn("data-sort='age' data-default='asc'>Age ▲", ascending)
        self.assertLess(ascending.index("Younger"), ascending.index("Older"))
        self.assertIn("Age ▼", descending)
        self.assertLess(descending.index("Older"), descending.index("Younger"))
        self.assertIn("name='dir' value='desc'", descending)

    def test_the_role_table_shows_the_median_too(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(id="a", name="Role Player", positions=("ST",), attributes={}, age=20),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, body = self._get(port, "/scouting?role=af_attack&position=ST")

        self.assertIn("<th>Median estimate</th>", body)

    def test_familiarity_columns_appear_only_when_the_raw_positions_box_is_ticked(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="a", name="Rated Defender", positions=("DC",), attributes={},
                    age=22, scouting_knowledge=12, raw_position_familiarity={"DC": 17, "DR": 4},
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _s, off = self._get(port, "/scouting?view=scouted&position=DC")
        _s, ticked = self._get(port, "/scouting?view=scouted&position=DC&includeRawPositions=1")

        self.assertIn("Rated Defender", off)
        self.assertNotIn("data-sort='adjusted'", off)   # the sort *button*, not the dropdown label
        self.assertNotIn("17/20", off)
        self.assertIn("data-sort='adjusted'", ticked)
        self.assertIn("In-position role score", ticked)
        self.assertIn("attribute-based", ticked)
        self.assertIn("17/20", ticked)
        self.assertIn("(×0.92)", ticked)

    def test_the_scouting_page_offers_a_rank_by_control(self) -> None:
        port = self._serve(FIXTURE)
        _status, body = self._get(port, "/scouting")

        self.assertIn("name='sort'", body)
        self.assertIn("Ceiling (best case)", body)

    def test_the_browse_table_shows_each_players_attributes(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-1", name="Sheet Player", positions=("ST",),
                    attributes={"pace": AttributeObservation(Visibility.RANGE, minimum=9, maximum=15)},
                    age=19, scouting_knowledge=12,
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, body = self._get(port, "/scouting?view=scouted")

        self.assertIn("<th>Attributes</th>", body)
        self.assertIn("9-15", body)

    def test_uncaptured_player_search_attributes_are_not_reported_as_none(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="uncaptured", name="Alex Robinson", positions=(),
                    raw_positions=("ML", "AML", "ST"), attributes={},
                    matched_active_search=True,
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, listing = self._get(port, "/scouting?includeRawPositions=1")
        status, report = self._get(port, "/scouting/player/uncaptured")

        self.assertIn("Not captured from FM", listing)
        self.assertNotIn("No attributes captured", listing)
        self.assertEqual(status, 200)
        self.assertIn("This does not mean FM shows no attributes", report)
        self.assertIn("Capture the current Player Search attributes", report)

    def test_a_scouted_player_links_to_an_exhaustive_scouting_report(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="report player/1", name="Report Player", positions=("ST",),
                    attributes={
                        "pace": AttributeObservation(Visibility.KNOWN, value=16),
                        "finishing": AttributeObservation(Visibility.RANGE, minimum=12, maximum=16),
                    },
                    age=21, scouting_knowledge=82,
                    raw_position_familiarity={"ST": 18, "AMR": 7},
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, listing = self._get(port, "/scouting?view=scouted")
        status, report = self._get(port, "/scouting/player/report%20player%2F1")

        self.assertIn("href='/scouting/player/report%20player%2F1'", listing)
        self.assertEqual(status, 200)
        self.assertIn("Current attributes", report)
        self.assertIn("Tactic impact", report)
        self.assertIn("Analyse player", report)
        self.assertIn("Pace", report)
        self.assertIn("16", report)
        self.assertIn("12-16", report)
        self.assertIn("Position familiarity", report)
        self.assertIn("18/20", report)
        self.assertIn("AMR", report)
        self.assertIn("Position score summary", report)
        self.assertIn("Best role (by estimate)", report)
        self.assertIn("In-position estimate", report)
        self.assertIn("All attribute-based role scores by position", report)
        self.assertIn("Advanced Forward (Attack)", report)
        self.assertIn("Attribute score inputs", report)

    def test_past_attributes_are_dated_separately_and_never_claimed_as_current(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="past-player", name="Past Player", positions=("ST",),
                    attributes={}, scouting_knowledge=6,
                    dropped_from_scout_reports=True,
                    last_known_attributes={
                        "pace": AttributeObservation(
                            Visibility.RANGE, minimum=8, maximum=14
                        )
                    },
                    last_known_attributes_observed_at="2019-07-21",
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, listing = self._get(port, "/scouting?view=scouted")
        status, report = self._get(port, "/scouting/player/past-player")

        self.assertIn("<th>Past knowledge</th>", listing)
        self.assertIn("1 ranged", listing)
        self.assertIn("Last visible 2019-07-21", listing)
        self.assertEqual(status, 200)
        self.assertIn("Current attributes", report)
        self.assertIn("No attributes currently visible", report)
        self.assertIn("Past scouting knowledge", report)
        self.assertIn("last visible on <b>2019-07-21</b>", report)
        self.assertIn("8-14", report)
        self.assertIn("not used in any score, filter, or recommendation", report)

    def test_a_missing_scouting_report_player_returns_not_found(self) -> None:
        port = self._serve(FIXTURE)

        status, body = self._get(port, "/scouting/player/missing")

        self.assertEqual(status, 404)
        self.assertIn("not in the current scouting capture", body)

    def test_scouting_refresh_button_runs_the_configured_capture(self) -> None:
        calls = []

        def refresh(*, allow_rebuild=False):
            calls.append(allow_rebuild)
            return "Captured scouting data"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        status, location, _body = self._post(port, "/scouting/refresh")
        refreshed_status, refreshed_body = self._get(port, "/scouting?refreshed=1")

        self.assertEqual(status, 303)
        self.assertEqual(location, "/scouting?refreshed=1")
        self.assertEqual(calls, [False])
        self.assertEqual(refreshed_status, 200)
        self.assertIn("Refresh Player Search and attributes", refreshed_body)
        self.assertIn("Scouting data refreshed", refreshed_body)

    def test_all_players_can_capture_the_active_fm_search_attributes(self) -> None:
        calls = []

        def refresh(*, allow_rebuild=False, hydrate_active_search=False):
            calls.append((allow_rebuild, hydrate_active_search))
            return "Captured active search attributes"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        _page_status, page = self._get(port, "/scouting?view=all")
        status, location, _body = self._post(
            port, "/scouting/refresh", "hydrate_active_search=1"
        )
        _refreshed_status, refreshed = self._get(port, location)

        self.assertIn("Refresh Player Search and attributes", page)
        self.assertIn("name='hydrate_active_search' value='1'", page)
        self.assertEqual(status, 303)
        self.assertEqual(location, "/scouting?refreshed=hydrated")
        self.assertEqual(calls, [(False, True)])
        self.assertIn("current visible attributes", refreshed)
        self.assertIn("inside the running game", refreshed)

    def test_scouted_refresh_uses_reports_without_player_search_hydration(self) -> None:
        calls = []

        def refresh(*, allow_rebuild=False, hydrate_active_search=False):
            calls.append((allow_rebuild, hydrate_active_search))
            return "Captured current scout reports"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        _page_status, page = self._get(port, "/scouting?view=scouted")
        status, location, _body = self._post(
            port, "/scouting/refresh", "return_view=scouted"
        )

        self.assertIn("Refresh scouted players", page)
        self.assertNotIn("name='hydrate_active_search' value='1'", page)
        self.assertEqual(status, 303)
        self.assertEqual(location, "/scouting?view=scouted&refreshed=1")
        self.assertEqual(calls, [(False, False)])

    def test_active_search_refresh_passes_the_hydration_flag_to_the_capture_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "fm_analytics.web.rendering.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "Captured active search attributes"
            run.return_value.stderr = ""

            message = _scouting_refresh_command(
                Path(directory) / "scouting.json"
            )(hydrate_active_search=True)

        command = run.call_args.args[0]
        self.assertIn("--hydrate-active-search", command)
        self.assertEqual(message, "Captured active search attributes")

    def test_refresh_defaults_to_no_rebuild_and_says_nothing_was_written(self) -> None:
        """The plain button must never carry consent to run FM's code."""
        def refresh(*, allow_rebuild=False):
            self.assertFalse(allow_rebuild)
            return "Captured scouting data"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        _status, location, _body = self._post(port, "/scouting/refresh")
        _refreshed_status, refreshed_body = self._get(port, location)

        self.assertIn("Nothing was written to FM", refreshed_body)

    def test_unbuilt_pool_offers_a_choice_instead_of_rebuilding(self) -> None:
        def refresh(*, allow_rebuild=False):
            self.assertFalse(allow_rebuild)
            raise ScoutingPoolNotBuilt("FM has not built this manager's pool yet.")

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        status, _location, body = self._post(port, "/scouting/refresh")

        self.assertEqual(status, 409)
        self.assertIn("Player Search", body)
        self.assertIn("Nothing has been sent to FM", body)
        self.assertIn("allow_rebuild", body)

    def test_rebuild_happens_only_when_the_form_carries_consent(self) -> None:
        calls = []

        def refresh(*, allow_rebuild=False):
            calls.append(allow_rebuild)
            return "Captured scouting data"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        status, location, _body = self._post(
            port, "/scouting/refresh", "allow_rebuild=1"
        )
        _refreshed_status, refreshed_body = self._get(port, location)

        self.assertEqual(status, 303)
        self.assertEqual(calls, [True])
        self.assertEqual(location, "/scouting?refreshed=rebuilt")
        self.assertIn("inside the running game", refreshed_body)

    def test_scouting_page_requires_opt_in_for_raw_external_positions(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-raw",
                    name="Raw Position Striker",
                    positions=(),
                    raw_positions=("ST",),
                    attributes={},
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        hidden_status, hidden_body = self._get(port, "/scouting?position=ST")
        shown_status, shown_body = self._get(
            port,
            "/scouting?position=ST&includeRawPositions=1",
        )

        self.assertEqual(hidden_status, 200)
        self.assertNotIn("Raw Position Striker", hidden_body)
        self.assertEqual(shown_status, 200)
        self.assertIn("Raw Position Striker", shown_body)
        self.assertIn("Raw external positions enabled", shown_body)
        self.assertIn("raw external data", shown_body)
        self.assertIn("Ranked for ST", shown_body)

    def test_scouting_page_explains_when_an_old_capture_has_no_raw_positions(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-no-raw",
                    name="No Raw Position",
                    positions=(),
                    attributes={},
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        status, body = self._get(port, "/scouting?includeRawPositions=1")

        self.assertEqual(status, 200)
        self.assertIn("Raw external positions enabled, but unavailable", body)

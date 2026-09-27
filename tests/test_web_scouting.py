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

        self.assertIn("data-sort='median'", body)
        self.assertIn(">Median</button>", body)

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

    def _mixed_pool(self):
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="a", name="Older Striker", positions=("ST",), attributes={},
                    age=31, club="Alpha", value=900_000, scouting_knowledge=9,
                ),
                ScoutingCandidate(
                    id="b", name="Younger Striker", positions=("ST",), attributes={},
                    age=18, club="Beta", value=50_000, scouting_knowledge=9,
                ),
                # Never scouted: on the All tab only.
                ScoutingCandidate(
                    id="c", name="Unscouted Midfielder", positions=("MC",), attributes={},
                    age=24, club="Gamma", value=300_000,
                ),
            )

        return self._serve(FIXTURE, scouting_provider)

    def test_every_results_table_sorts_on_the_server(self) -> None:
        """The complaint this guards: sorting used to exist only under some filters."""
        port = self._mixed_pool()
        views = {
            "all players, nothing chosen": "",
            "scouted tab": "view=scouted",
            "a position": "position=ST",
            "a role": "role=af_attack",
            "a role and position": "role=af_attack&position=ST",
        }
        for label, query in views.items():
            with self.subTest(view=label):
                joined = query + "&" if query else ""
                _s, ascending = self._get(port, f"/scouting?{joined}sort=age&dir=asc")
                _s, descending = self._get(port, f"/scouting?{joined}sort=age&dir=desc")

                self.assertIn("data-sort='age' data-default='asc'>Age ▲", ascending)
                self.assertIn("aria-sort='ascending'", ascending)
                self.assertIn("Age ▼", descending)
                self.assertLess(ascending.index("Younger Striker"), ascending.index("Older Striker"))
                self.assertLess(descending.index("Older Striker"), descending.index("Younger Striker"))

    def test_all_players_with_nothing_chosen_is_ranked_not_a_bare_list(self) -> None:
        port = self._mixed_pool()
        _s, body = self._get(port, "/scouting")

        self.assertIn("Ranked, all positions (3)", body)
        self.assertIn("Unscouted Midfielder", body)
        for column in ("median", "minimum", "ceiling", "value", "age", "name"):
            self.assertIn(f"data-sort='{column}'", body)

    def test_the_role_table_offers_its_scouting_order_as_a_sort(self) -> None:
        port = self._mixed_pool()
        _s, body = self._get(port, "/scouting?role=af_attack&position=ST")

        self.assertIn("data-sort='priority'", body)
        self.assertIn("Sorted by <b>Scouting priority</b> (high to low)", body)
        # No "best role" column when the role is already chosen.
        self.assertNotIn("data-sort='role'", body)

    def test_a_sort_from_another_table_falls_back_to_this_tables_default(self) -> None:
        port = self._mixed_pool()
        _s, ranking = self._get(port, "/scouting?sort=tactic_gain")
        _s, role = self._get(port, "/scouting?role=af_attack&sort=role")
        _s, role_median = self._get(port, "/scouting?role=af_attack&sort=median")

        self.assertIn("Sorted by <b>Median (best guess)</b>", ranking)
        self.assertIn("Sorted by <b>Scouting priority</b>", role)
        self.assertIn("Sorted by <b>Median (best guess)</b>", role_median)

    def test_the_sort_list_only_offers_columns_the_current_table_has(self) -> None:
        port = self._mixed_pool()
        _s, ranking = self._get(port, "/scouting")
        _s, role = self._get(port, "/scouting?role=af_attack")

        def enabled(body: str, key: str) -> bool:
            option = body[body.index(f"<option value='{key}' data-modes"):]
            return "hidden disabled" not in option[: option.index("</option>")]

        self.assertTrue(enabled(ranking, "median"))
        self.assertFalse(enabled(ranking, "tactic_gain"))
        self.assertFalse(enabled(ranking, "priority"))
        self.assertTrue(enabled(role, "priority"))
        self.assertFalse(enabled(role, "role"))

    def test_visibility_and_score_filters_apply_when_no_role_is_chosen(self) -> None:
        """They used to be ignored until a role was picked."""
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="known", name="Fully Known", positions=("ST",), age=25,
                    attributes={
                        name: AttributeObservation(Visibility.KNOWN, value=18)
                        for name in required_role_attributes()
                    },
                    attributes_observed_at="2019-07-21",
                ),
                ScoutingCandidate(
                    id="blank", name="Nothing Known", positions=("ST",), age=25,
                    attributes={}, attributes_observed_at="2019-07-21",
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _s, known = self._get(port, "/scouting?visibility=known")
        _s, unknown = self._get(port, "/scouting?visibility=unknown")
        _s, high_floor = self._get(port, "/scouting?minFloor=60")

        self.assertIn("Fully Known", known)
        self.assertNotIn("Nothing Known", known)
        self.assertIn("Nothing Known", unknown)
        self.assertNotIn("Fully Known", unknown)
        self.assertIn("Fully Known", high_floor)
        self.assertNotIn("Nothing Known", high_floor)

    def test_show_more_extends_the_page_beyond_the_default_row_count(self) -> None:
        def scouting_provider():
            return tuple(
                ScoutingCandidate(
                    id=f"p{index}", name=f"Player {index:03d}", positions=("ST",),
                    attributes={}, age=20 + index % 10,
                )
                for index in range(130)
            )

        port = self._serve(FIXTURE, scouting_provider)
        _s, first = self._get(port, "/scouting/results?sort=name&dir=asc")
        _s, more = self._get(port, "/scouting/results?sort=name&dir=asc&limit=200")

        self.assertIn("Showing 100 of 130", first)
        self.assertIn("data-limit='200'", first)
        self.assertNotIn("Player 129", first)
        self.assertIn("Player 129", more)
        self.assertNotIn("show-more", more)

    def test_the_role_select_lists_every_role_until_a_position_narrows_it(self) -> None:
        port = self._mixed_pool()
        _s, everything = self._get(port, "/scouting")
        _s, narrowed = self._get(port, "/scouting?position=GK")

        self.assertNotIn("disabled>Choose a position first", everything)
        self.assertIn("Advanced Forward (Attack)", everything)
        select = narrowed[narrowed.index("<select name='role'>"):]
        select = select[: select.index("</select>")]
        self.assertNotIn("Advanced Forward", select)
        self.assertIn("Goalkeeper", select)

    def test_filter_groups_open_when_one_of_their_filters_is_set(self) -> None:
        port = self._mixed_pool()
        _s, plain = self._get(port, "/scouting")
        _s, filtered = self._get(port, "/scouting?maxAge=21&club=Beta")

        self.assertNotIn("<details class='filter-group' open>", plain)
        self.assertIn("<details class='filter-group' open>", filtered)
        self.assertIn("2 set", filtered)
        self.assertIn("Reset filters", filtered)

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

        self.assertIn("Past knowledge</th>", listing)
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
        self.assertIn("Refresh scouting data", refreshed_body)
        self.assertIn("Scouting data refreshed", refreshed_body)

    def test_all_players_main_refresh_never_runs_fm_code(self) -> None:
        """Saves broke on 26 September 2026 when a button hydrated by running FM's
        code live; the sandbox (tools.fm20_sandbox_queries) replaced that path
        outright on 27 September, so there is only ever this one, safe button."""
        calls = []

        def refresh(*, allow_rebuild=False):
            calls.append(allow_rebuild)
            return "Captured scouting data"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        _page_status, page = self._get(port, "/scouting?view=all")
        panel = page[page.index("<section class='refresh-panel'>"):]
        main_form = panel[:panel.index("</form>")]
        status, location, _body = self._post(port, "/scouting/refresh", "return_view=all")
        _refreshed_status, refreshed = self._get(port, location)

        self.assertIn("Refresh scouting data", main_form)
        self.assertNotIn("danger", main_form)
        self.assertEqual(status, 303)
        self.assertEqual(location, "/scouting?view=all&refreshed=1")
        self.assertEqual(calls, [False])
        self.assertIn("Nothing was written to FM", refreshed)

    def test_scouted_refresh_reads_reports_only(self) -> None:
        calls = []

        def refresh(*, allow_rebuild=False):
            calls.append(allow_rebuild)
            return "Captured current scout reports"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        _page_status, page = self._get(port, "/scouting?view=scouted")
        status, location, _body = self._post(
            port, "/scouting/refresh", "return_view=scouted"
        )

        self.assertIn("Refresh scouted players", page)
        self.assertEqual(status, 303)
        self.assertEqual(location, "/scouting?view=scouted&refreshed=1")
        self.assertEqual(calls, [False])

    def test_refresh_command_passes_allow_rebuild_through_to_the_capture_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "fm_analytics.web.rendering.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "Captured scouting data"
            run.return_value.stderr = ""

            message = _scouting_refresh_command(
                Path(directory) / "scouting.json"
            )(allow_rebuild=True)

        command = run.call_args.args[0]
        self.assertIn("--allow-rebuild", command)
        self.assertNotIn("--hydrate-active-search", command)
        self.assertEqual(message, "Captured scouting data")

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

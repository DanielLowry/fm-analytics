import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.persistence import PlayerKnowledgeStore, Verdict
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

    def test_trial_priority_explains_its_rule_and_keeps_unscored_players_separate(self) -> None:
        required = required_role_attributes()

        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="ready", name="Ready Target", positions=("ST",),
                    attributes={name: AttributeObservation(Visibility.KNOWN, value=20) for name in required},
                    in_player_search=True, transfer_interest="yes", attributes_observed_at="2019-07-21",
                ),
                ScoutingCandidate(
                    id="scout", name="Scout Target", positions=("ST",), attributes={},
                    in_player_search=True, loan_interest="maybe", attributes_observed_at="2019-07-21",
                ),
                ScoutingCandidate(
                    id="not-gettable", name="Not Gettable", positions=("ST",), attributes={},
                    in_player_search=True, attributes_observed_at="2019-07-21",
                ),
            )

        with tempfile.TemporaryDirectory() as directory:
            port = self._serve(write_complete_fixture(Path(directory)), scouting_provider)
            status, body = self._get(port, "/scouting?tactic=balanced_442&sort=trial_priority")

        self.assertEqual(status, 200)
        self.assertIn("Trial priority", body)
        self.assertIn("Median scenario", body)
        self.assertIn("choosing whom to look at, never whom to sign", body)
        self.assertIn("Ready Target", body)
        self.assertIn("Scout first", body)
        self.assertIn("Scout Target", body)
        self.assertNotIn("Not Gettable", body)

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

    def test_the_scouted_tab_matches_fm_until_everyone_ever_scouted_is_ticked(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="current", name="Current Report", positions=("ST",), attributes={},
                    scouting_knowledge=40, has_scout_report=True,
                ),
                ScoutingCandidate(
                    id="former", name="Former Report", positions=("ST",), attributes={},
                    scouting_knowledge=6, has_scout_report=True, dropped_from_scout_reports=True,
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, default = self._get(port, "/scouting?view=scouted")
        _status, everyone = self._get(port, "/scouting?view=scouted&everScouted=1")

        self.assertIn("Current Report", default)
        self.assertNotIn("Former Report", default)
        self.assertIn("name='everScouted' type='checkbox' value='1'>", default)
        self.assertIn("Former Report", everyone)
        self.assertIn("name='everScouted' type='checkbox' value='1' checked>", everyone)

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
        _status, listing = self._get(port, "/scouting?view=scouted&everScouted=1")
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
        refreshed_status, refreshed_body = self._get(port, "/scouting?refreshed=started")

        self.assertEqual(status, 303)
        self.assertEqual(location, "/scouting?refreshed=started")
        self.assertEqual(calls, [False])
        self.assertEqual(refreshed_status, 200)
        self.assertIn("Refresh scouting data", refreshed_body)
        self.assertIn("Refresh succeeded", refreshed_body)
        self.assertIn("Captured scouting data", refreshed_body)

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
        self.assertEqual(location, "/scouting?view=all&refreshed=started")
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
        self.assertEqual(location, "/scouting?view=scouted&refreshed=started")
        self.assertEqual(calls, [False])

    def test_refresh_command_passes_allow_rebuild_through_to_the_capture_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "fm_analytics.web.rendering.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "Captured scouting data"
            run.return_value.stderr = ""

            target = Path(directory) / "scouting.json"
            target.write_text('{"old": true}', encoding="utf-8")
            def capture(*_args, **_kwargs):
                target.with_suffix(".json.tmp").write_text('{"players": []}', encoding="utf-8")
                return run.return_value

            run.side_effect = capture

            message = _scouting_refresh_command(
                target
            )(allow_rebuild=True)
            self.assertEqual(target.read_text(encoding="utf-8"), '{"players": []}')
            self.assertFalse(target.with_suffix(".json.tmp").exists())

        command = run.call_args.args[0]
        self.assertIn("--allow-rebuild", command)
        self.assertNotIn("--hydrate-active-search", command)
        self.assertNotIn("--replace", command)
        self.assertEqual(command[command.index("--output") + 1], str(target) + ".tmp")
        self.assertEqual(command[command.index("--base-feed") + 1], str(target))
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
        status, location, _body = self._post(port, "/scouting/refresh")
        time.sleep(0.02)
        _page_status, body = self._get(port, location)

        self.assertEqual(status, 303)
        self.assertIn("Refresh failed", body)
        self.assertIn("Player Search", body)

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
        self.assertEqual(location, "/scouting?refreshed=started")
        self.assertIn("Refresh", refreshed_body)
        self.assertIn("save risk", refreshed_body)
        self.assertNotIn("Nothing was written to FM", refreshed_body)

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


class ScoutingVerdictTests(WebServerHelpers, unittest.TestCase):
    """The manager's own Target / Watch / Reject decisions, end to end.

    Verdicts live in the local player-knowledge database only: no test here
    uses a scouting refresh, and none of them can write to FM.
    """

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = PlayerKnowledgeStore(Path(directory.name) / "knowledge.sqlite3")
        self.store.initialize()
        self.save_key = "club:1"

    @staticmethod
    def _candidates():
        return (
            ScoutingCandidate(
                id="otto", name="Otto Striker", positions=("ST",), attributes={},
                age=22, club="Example FC", scouting_knowledge=100,
                captured_game_date="2019-09-08",
            ),
            ScoutingCandidate(
                id="ned", name="Ned Prospect", positions=("ST",), attributes={},
                age=19, club="Example FC", scouting_knowledge=100,
                captured_game_date="2019-09-08",
            ),
        )

    def _serve(self, candidates=None, **server_kwargs):
        pool = self._candidates() if candidates is None else candidates
        server_kwargs.setdefault("knowledge_store", self.store)
        server_kwargs.setdefault("knowledge_save_key", self.save_key)
        return super()._serve(FIXTURE, lambda: pool, **server_kwargs)

    def _save(self, port: int, player_id: str, verdict: str, note: str = "") -> tuple[int, str | None, str]:
        return self._post(
            port,
            "/scouting/verdict",
            f"player_id={player_id}&verdict={verdict}&note={note}"
            "&decidedOn=2019-09-08&action=save",
        )

    def _count_verdicts(self) -> int:
        with closing(sqlite3.connect(self.store.path)) as connection:
            return connection.execute("SELECT COUNT(*) FROM verdict_events").fetchone()[0]

    def test_the_report_offers_a_verdict_form_dated_by_the_capture(self) -> None:
        port = self._serve()
        status, body = self._get(port, "/scouting/player/otto")

        self.assertEqual(status, 200)
        self.assertIn("action='/scouting/verdict'", body)
        self.assertIn("name='player_id' value='otto'", body)
        self.assertIn("name='decidedOn' value='2019-09-08'", body)
        self.assertIn("No verdict recorded yet", body)
        self.assertIn("FM is never told", body)

    def test_saving_a_verdict_redirects_to_the_report_and_shows_it(self) -> None:
        port = self._serve()
        status, location, _body = self._save(port, "otto", "target", "fast+and+left-footed")

        self.assertEqual(status, 303)
        self.assertEqual(location, "/scouting/player/otto")
        report_status, body = self._get(port, location)

        self.assertEqual(report_status, 200)
        self.assertIn("Current verdict: <b>Target</b>", body)
        self.assertIn("fast and left-footed", body)
        self.assertIn("decided 2019-09-08", body)
        record = self.store.get_verdict(self.save_key, "otto")
        self.assertEqual((record.verdict, record.note), (Verdict.TARGET, "fast and left-footed"))

    def test_resubmitting_the_same_verdict_keeps_a_single_decision(self) -> None:
        port = self._serve()
        self._save(port, "otto", "watch")
        status, location, _body = self._save(port, "otto", "watch")

        self.assertEqual((status, location), (303, "/scouting/player/otto"))
        self.assertEqual(self._count_verdicts(), 1)

    def test_a_note_is_escaped_and_never_rendered_as_markup(self) -> None:
        port = self._serve()
        self._save(port, "otto", "target", "fast+%3Cb%3Ewinger%3C%2Fb%3E")
        _status, body = self._get(port, "/scouting/player/otto")

        self.assertIn("fast &lt;b&gt;winger&lt;/b&gt;", body)
        self.assertNotIn("<b>winger</b>", body)

    def test_clearing_forgets_the_decision_but_keeps_what_was_made(self) -> None:
        port = self._serve()
        self._save(port, "otto", "reject")
        status, location, _body = self._post(
            port, "/scouting/verdict", "player_id=otto&decidedOn=2019-10-01&action=clear"
        )

        self.assertEqual((status, location), (303, "/scouting/player/otto"))
        self.assertIsNone(self.store.get_verdict(self.save_key, "otto"))
        self.assertEqual(self._count_verdicts(), 2)
        _report_status, body = self._get(port, location)
        self.assertIn("No verdict recorded yet", body)

    def test_rejecting_a_player_hides_him_from_the_list_until_shown_again(self) -> None:
        port = self._serve()
        self._save(port, "otto", "reject")

        _status, hidden = self._get(port, "/scouting?position=ST")
        _status, shown = self._get(port, "/scouting?position=ST&showRejected=1")
        _status, filtered = self._get(port, "/scouting?position=ST&showRejected=1&name=Otto")

        self.assertIn("Ned Prospect", hidden)
        self.assertNotIn("Otto Striker", hidden)
        self.assertIn("Otto Striker", shown)
        self.assertIn("Ned Prospect", shown)
        # Show rejected is a view switch: the other filters still apply.
        self.assertIn("Otto Striker", filtered)
        self.assertNotIn("Ned Prospect", filtered)
        self.assertIn("checked> Show rejected players", shown)
        # The rejected player keeps his own report; only the list changed.
        report_status, body = self._get(port, "/scouting/player/otto")
        self.assertEqual(report_status, 200)
        self.assertIn("Current verdict: <b>Reject</b>", body)

    def test_the_live_results_fragment_hides_rejects_like_the_full_page(self) -> None:
        port = self._serve()
        self._save(port, "otto", "reject")

        _status, hidden = self._get(port, "/scouting/results?position=ST")
        _status, shown = self._get(port, "/scouting/results?position=ST&showRejected=1")

        self.assertNotIn("Otto Striker", hidden)
        self.assertIn("Ned Prospect", hidden)
        self.assertIn("Otto Striker", shown)

    def test_a_verdict_without_a_capture_date_is_shown_but_not_editable(self) -> None:
        candidate = ScoutingCandidate(
            id="dated-none", name="No Capture Date", positions=("ST",), attributes={},
            age=20, scouting_knowledge=100, captured_game_date=None,
        )
        self.store.set_verdict(
            self.save_key, "dated-none", Verdict.WATCH, note="heard of him",
            decided_on="2019-09-08",
        )
        port = self._serve((candidate,))
        status, body = self._get(port, "/scouting/player/dated-none")

        self.assertEqual(status, 200)
        self.assertIn("Current verdict: <b>Watch</b>", body)
        self.assertIn("heard of him", body)
        self.assertNotIn("action='/scouting/verdict'", body)

    def test_an_unusable_submission_is_refused_without_writing_anything(self) -> None:
        port = self._serve()
        bad_verdict = self._save(port, "otto", "maybe")
        _status, _location, oversized = self._post(
            port, "/scouting/verdict",
            "player_id=otto&verdict=target&note=" + ("x" * 501) + "&decidedOn=2019-09-08&action=save",
        )
        _status, _location, bad_date = self._post(
            port, "/scouting/verdict", "player_id=otto&verdict=target&decidedOn=yesterday&action=save"
        )
        _status, _location, no_player = self._post(
            port, "/scouting/verdict", "verdict=target&action=save"
        )
        _status, _location, bad_action = self._post(
            port, "/scouting/verdict", "player_id=otto&verdict=target&decidedOn=2019-09-08&action=delete"
        )

        self.assertEqual((bad_verdict[0], bad_verdict[1]), (400, None))
        for body in (oversized, bad_date, no_player, bad_action):
            self.assertIn("Verdict", body)
        self.assertIsNone(self.store.get_verdict(self.save_key, "otto"))
        self.assertEqual(self._count_verdicts(), 0)

    def test_a_verdict_touches_neither_the_scouting_refresh_nor_the_recorder(self) -> None:
        """The brief's hard rule: verdicts are local, manager-authored data only."""
        refreshes: list = []
        recordings: list = []

        def refresh(**kwargs):
            refreshes.append(kwargs)
            return "refreshed"

        def record():
            recordings.append(True)
            raise AssertionError("saving a verdict must not record a capture")

        port = self._serve(scouting_refresh=refresh, knowledge_recorder=record)
        status, location, _body = self._save(port, "otto", "target")

        self.assertEqual((status, location), (303, "/scouting/player/otto"))
        self.assertEqual(refreshes, [])
        self.assertEqual(recordings, [])
        self.assertEqual(self._count_verdicts(), 1)

    def test_without_a_verdict_store_the_report_is_exactly_as_it_was(self) -> None:
        server_kwargs = {"knowledge_store": None, "knowledge_save_key": None}
        port = self._serve(**server_kwargs)
        report_status, body = self._get(port, "/scouting/player/otto")
        list_status, listing = self._get(port, "/scouting?position=ST")

        self.assertEqual(report_status, 200)
        self.assertNotIn("action='/scouting/verdict'", body)
        self.assertNotIn("Signing verdict", body)
        self.assertEqual(list_status, 200)
        self.assertIn("Otto Striker", listing)

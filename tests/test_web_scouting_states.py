"""Each visibility / history state the scouting list and report distinguish.

docs/tasks/low-scouting-state-regression-coverage.md. One named builder per
state, changing only the field that defines it, so a failing assertion names
the state that broke rather than a shared pile of options; every builder is
then read back from both the roster row and the player report.

Split out of test_web_scouting.py so that the module stays a size that can
be read in one sitting (tests/test_line_caps.py).
"""

import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes
from fm_analytics.analytics import (
    MVP_CATALOGUE,
    CandidateHistory,
    HistoricalReading,
    ScoutingCandidate,
)
from tests.web_support import FIXTURE, WebServerHelpers, write_complete_fixture


# --- One named fixture per visibility / history state ----------------------
# docs/tasks/low-scouting-state-regression-coverage.md: every state the
# scouting list and the player report distinguish gets a builder of its own,
# changing only the field that defines that state, so a failing assertion
# names the state that broke rather than a shared pile of options.

OBSERVED_ON = "2019-07-21"
CAPTURE_DATE = "2019-09-08"
AF_ATTACK_ATTRIBUTE_COUNT = len(MVP_CATALOGUE.roles["af_attack"].attributes)


def _every_role_attribute(visibility: Visibility, **values) -> dict:
    return {
        name: AttributeObservation(visibility, **values)
        for name in required_role_attributes()
    }


def current_exact_player() -> ScoutingCandidate:
    """Every role attribute is an exact value FM shows this manager today."""
    return ScoutingCandidate(
        id="state-exact",
        name="Exact Value Player",
        positions=("ST",),
        attributes=_every_role_attribute(Visibility.KNOWN, value=15),
        attributes_observed_at=OBSERVED_ON,
        age=24,
        club="Example FC",
        scouting_knowledge=100,
        has_scout_report=True,
        captured_game_date=CAPTURE_DATE,
    )


def current_range_player() -> ScoutingCandidate:
    """Every role attribute is a scouted min-max range, still current."""
    return ScoutingCandidate(
        id="state-range",
        name="Ranged Value Player",
        positions=("ST",),
        attributes=_every_role_attribute(Visibility.RANGE, minimum=9, maximum=15),
        attributes_observed_at=OBSERVED_ON,
        age=23,
        club="Example FC",
        scouting_knowledge=70,
        has_scout_report=True,
        captured_game_date=CAPTURE_DATE,
    )


def captured_unknown_player() -> ScoutingCandidate:
    """FM's current answer was read and said "unknown" for every attribute.

    Captured -- an empty-looking sheet is a real FM answer here -- which is
    what separates this state from :func:`uncaptured_player`.
    """
    return ScoutingCandidate(
        id="state-unknown",
        name="Captured Unknown Player",
        positions=("ST",),
        attributes=_every_role_attribute(Visibility.UNKNOWN),
        attributes_observed_at=OBSERVED_ON,
        age=21,
        club="Example FC",
        scouting_knowledge=5,
        has_scout_report=True,
        captured_game_date=CAPTURE_DATE,
    )


def uncaptured_player() -> ScoutingCandidate:
    """Nobody has ever read this player's current visible attributes."""
    return ScoutingCandidate(
        id="state-uncaptured",
        name="Uncaptured Player",
        positions=("ST",),
        attributes={},
        age=20,
        club="Example FC",
        captured_game_date=CAPTURE_DATE,
    )


def carried_historical_player() -> ScoutingCandidate:
    """Known only from the knowledge history carried forward from earlier in
    this save: not in the current feed at all, so none of it is current."""
    return ScoutingCandidate(
        id="state-carried",
        name="Carried History Player",
        positions=("ST",),
        attributes={
            "pace": AttributeObservation(Visibility.RANGE, minimum=8, maximum=14),
        },
        age=27,
        scouting_knowledge=40,
        has_scout_report=True,
        captured_game_date=CAPTURE_DATE,
        history=CandidateHistory(
            as_of=CAPTURE_DATE,
            in_current_feed=False,
            out_of_date_before="2019-08-01",
            attributes={
                "pace": HistoricalReading(
                    observed_on=OBSERVED_ON,
                    last_seen_on=OBSERVED_ON,
                    source="current",
                ),
            },
            profile={"club": "Old Club"},
            profile_last_seen_on=OBSERVED_ON,
        ),
    )


def dropped_from_reports_player() -> ScoutingCandidate:
    """Still in Player Search, but off FM's scout reports: the sheet he once
    had is the separately dated ``last_known_attributes`` snapshot."""
    return ScoutingCandidate(
        id="state-dropped",
        name="Dropped Report Player",
        positions=("ST",),
        attributes={},
        attributes_observed_at=OBSERVED_ON,
        age=29,
        club="Example FC",
        scouting_knowledge=40,
        has_scout_report=True,
        dropped_from_scout_reports=True,
        in_player_search=True,
        captured_game_date=CAPTURE_DATE,
        last_known_attributes={
            "pace": AttributeObservation(Visibility.RANGE, minimum=8, maximum=14)
        },
        last_known_attributes_observed_at=OBSERVED_ON,
    )


ALL_STATE_PLAYERS = (
    current_exact_player(),
    current_range_player(),
    captured_unknown_player(),
    uncaptured_player(),
    carried_historical_player(),
    dropped_from_reports_player(),
)


class ScoutingStateTests(WebServerHelpers, unittest.TestCase):
    """Lock down each visibility/history state on the list cell and the report.

    ``docs/tasks/low-scouting-state-regression-coverage.md``. Exact, range,
    captured-unknown, never-captured, carried-historical and dropped are
    easy to collapse into one another by accident, and the recruitment work
    scheduled next builds on all six. Nothing here reads the player-knowledge
    database: the fixtures are plain domain objects.

    Two inconsistencies this task found are documented rather than fixed,
    because the brief reserves semantics and allows a production change only
    where ``docs/scouting-workspace.md`` already states the behaviour:

    1. Min / Median / Max and the tactic fit figures still render for the
       unknown and never-captured states (0.0 / 50.0 / 100.0 against an
       empty sheet). See
       ``test_unknown_and_uncaptured_states_get_no_invented_role_or_tactic_score``.
    2. The list's attribute-sheet group headings are always empty:
       ``scouting_render.attribute_sheet`` reuses ``title`` for both the
       group heading and the per-row historical tooltip, so the ``<h4>`` is
       blanked (and, for a remembered value, prints the literal tooltip
       text). The player report's own sheet -- ``scouting_report``'s
       ``_full_attribute_sheet`` -- renders the same groups correctly as
       ``<h3>Technical</h3>`` and friends. Not asserted here, so that fixing
       it does not have to break a test first.
    """

    def _serve_states(self, *candidates) -> int:
        return self._serve(FIXTURE, lambda: candidates)

    @staticmethod
    def _row(body: str, player_id: str) -> str:
        """The one results row for a player, matched on his stable link."""
        marker = f"/scouting/player/{player_id}"
        for row in re.findall(r"<tr>.*?</tr>", body, re.S):
            if marker in row:
                return row
        raise AssertionError(f"{player_id} has no row in the results table")

    @staticmethod
    def _section(report: str, heading: str) -> str:
        """The HTML between one ``<h2>`` heading and the next one."""
        start = report.index(heading) + len(heading)
        end = report.find("<h2>", start)
        return report[start: end if end != -1 else len(report)]

    def test_every_state_is_named_on_the_role_targets_table(self) -> None:
        """The first success criterion: one named fixture, one rendered label.

        ``everScouted`` is on because the carried-historical player is not in
        the current feed at all; it must never be the thing that hides the
        other five.
        """
        port = self._serve_states(*ALL_STATE_PLAYERS)
        status, body = self._get(
            port, "/scouting?role=af_attack&position=ST&everScouted=1"
        )

        self.assertEqual(status, 200)
        for player in ALL_STATE_PLAYERS:
            with self.subTest(player=player.name):
                self.assertIn(f"/scouting/player/{player.id}", body)
        for label in (
            "Proven fit",          # current exact
            "Scout to decide",     # current range
            "Scout first",         # captured unknown
            "Capture first",       # never captured
            "Not currently realistic",   # carried historical
            "used to be in the scouted pool",   # dropped from reports
        ):
            with self.subTest(label=label):
                self.assertIn(label, body)

    def test_a_current_exact_value_keeps_its_number(self) -> None:
        port = self._serve_states(current_exact_player())
        _s, listing = self._get(port, "/scouting?role=af_attack&position=ST")
        _s, report = self._get(port, "/scouting/player/state-exact")
        row = self._row(listing, "state-exact")

        self.assertIn(f"<b>{AF_ATTACK_ATTRIBUTE_COUNT} of {AF_ATTACK_ATTRIBUTE_COUNT} known</b>", row)
        self.assertNotIn(f"{AF_ATTACK_ATTRIBUTE_COUNT} ranged", row)
        self.assertNotIn(f"{AF_ATTACK_ATTRIBUTE_COUNT} unknown", row)
        self.assertIn("Proven fit", row)
        self.assertIn("<span>Pace</span><b>15</b>", row)
        self.assertIn("<td>Pace</td><td>15</td>", self._section(report, "<h2>Current attributes</h2>"))

    def test_a_current_range_keeps_both_ends(self) -> None:
        port = self._serve_states(current_range_player())
        _s, listing = self._get(port, "/scouting?role=af_attack&position=ST")
        _s, report = self._get(port, "/scouting/player/state-range")
        row = self._row(listing, "state-range")

        self.assertIn(f"0 of {AF_ATTACK_ATTRIBUTE_COUNT} known", row)
        self.assertIn(f"{AF_ATTACK_ATTRIBUTE_COUNT} ranged", row)
        self.assertNotIn(f"{AF_ATTACK_ATTRIBUTE_COUNT} unknown", row)
        self.assertIn("Scout to decide", row)
        self.assertIn("<span>Pace</span><b>9-15</b>", row)
        self.assertIn("<td>Pace</td><td>9-15</td>", self._section(report, "<h2>Current attributes</h2>"))
        self.assertIn("Ranges retain the uncertainty", report)

    def test_captured_unknown_and_never_captured_are_different_states(self) -> None:
        """The two are one empty-looking sheet apart and must never merge."""
        port = self._serve_states(captured_unknown_player(), uncaptured_player())
        _s, listing = self._get(port, "/scouting?role=af_attack&position=ST")
        unknown_row = self._row(listing, "state-unknown")
        uncaptured_row = self._row(listing, "state-uncaptured")
        _s, unknown_report = self._get(port, "/scouting/player/state-unknown")
        _s, uncaptured_report = self._get(port, "/scouting/player/state-uncaptured")

        # Captured: a real count of what FM's answer held, and a reason to scout.
        self.assertIn(f"0 of {AF_ATTACK_ATTRIBUTE_COUNT} known", unknown_row)
        self.assertIn(f"{AF_ATTACK_ATTRIBUTE_COUNT} unknown", unknown_row)
        self.assertIn("Scout first", unknown_row)
        self.assertNotIn("Not captured from FM", unknown_row)
        self.assertIn("<td>Pace</td><td>?</td>", unknown_report)

        # Never captured: a sentence, not a count, and a different next action.
        self.assertIn("Not captured from FM", uncaptured_row)
        self.assertNotRegex(uncaptured_row, rf"\d+ of \d+ known")
        self.assertNotIn("Scout first", uncaptured_row)
        self.assertIn("Capture first", uncaptured_row)
        self.assertIn("Not captured from FM.", uncaptured_report)
        self.assertNotIn("No attributes currently visible", uncaptured_report)

        self.assertNotIn("Not captured from FM", unknown_report)

    def test_unknown_and_uncaptured_values_are_never_rendered_as_numbers(self) -> None:
        """No attribute anyone can see is invented where nobody can see it."""
        port = self._serve_states(captured_unknown_player(), uncaptured_player())
        _s, listing = self._get(port, "/scouting?role=af_attack&position=ST")
        _s, unknown_report = self._get(port, "/scouting/player/state-unknown")
        _s, uncaptured_report = self._get(port, "/scouting/player/state-uncaptured")
        unknown_row = self._row(listing, "state-unknown")
        uncaptured_row = self._row(listing, "state-uncaptured")

        # The list sheet marks an unknown with a dash and never a figure.
        self.assertIn("<span>Pace</span><b>-</b>", unknown_row)
        self.assertNotIn("<span>Pace</span><b>15</b>", unknown_row)
        # The report marks it with a question mark.
        self.assertIn("<td>Pace</td><td>?</td>", unknown_report)
        # An uncaptured player has no attribute rows at all, in either place.
        self.assertIn("<span class='warn'>Not captured from FM</span>", uncaptured_row)
        self.assertNotIn("<td>Pace</td>", self._section(uncaptured_report, "<h2>Current attributes</h2>"))

    def test_unknown_and_uncaptured_states_get_no_invented_role_or_tactic_score(self) -> None:
        """A role score and a tactic score each need evidence before they exist.

        Role half: without a captured position-familiarity rating there is no
        in-position figure, only the word "Not captured" and an em dash --
        for the captured-unknown and the never-captured report alike.

        Tactic half: with no captured eligible position there is no tactic
        assessment at all, so the report explains why instead of printing a
        floor/estimate/ceiling nobody worked out.

        NOT asserted here, because it is ambiguous rather than obviously
        wrong: the plain Min / Median / Max columns and the tactic fit figures
        still render for these states (0.0 / 50.0 / 100.0 against an empty
        sheet). That is the documented all-unknown bound in
        ``docs/scouting-workspace.md`` ("an unscouted player scores 50"),
        while ``docs/active-plan.md`` item 3 says such a player is "not given
        an invented score" for the trial-priority list that does not exist
        yet. Redefining either one here would be choosing semantics the brief
        reserves, so it is escalated instead of silently made consistent.
        """
        port = self._serve_states(captured_unknown_player(), uncaptured_player())
        _s, unknown_report = self._get(port, "/scouting/player/state-unknown")
        _s, uncaptured_report = self._get(port, "/scouting/player/state-uncaptured")

        for report in (unknown_report, uncaptured_report):
            with self.subTest(report=report[:40]):
                self.assertIn("<td>Not captured</td><td>—</td>", report)
                self.assertNotRegex(
                    self._section(report, "<h2>Position familiarity</h2>"),
                    r"<td>\d+/20 \(×\d",
                )

        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            no_position = ScoutingCandidate(
                id="state-no-position",
                name="No Captured Position Player",
                positions=(),
                attributes={},
                captured_game_date=CAPTURE_DATE,
            )
            tactic_port = self._serve(fixture_path, lambda: (no_position,))
            _s, report = self._get(
                tactic_port, "/scouting/player/state-no-position?tactic=balanced_442"
            )
            _s, listing = self._get(tactic_port, "/scouting?tactic=balanced_442")

        self.assertIn("This player has no captured eligible position in this tactic.", report)
        self.assertNotIn("Projected tactic score", report)
        self.assertNotIn("No Captured Position Player", listing)

    def test_carried_historical_values_are_dated_and_never_current(self) -> None:
        port = self._serve_states(carried_historical_player())
        # Not in the current feed: only "everyone ever scouted" lists him.
        _s, hidden = self._get(port, "/scouting?role=af_attack&position=ST")
        _s, listing = self._get(
            port, "/scouting?role=af_attack&position=ST&everScouted=1"
        )
        _s, report = self._get(port, "/scouting/player/state-carried")
        row = self._row(listing, "state-carried")

        self.assertNotIn("/scouting/player/state-carried", hidden)
        self.assertIn("Not currently realistic", row)
        self.assertIn("Last seen at Old Club, 2019-07-21", row)
        self.assertIn("<b>1 from history</b>", row)
        self.assertIn("Out of date: oldest seen 2019-07-21", row)
        self.assertIn("Attributes (1 shown, 1 historical)", row)

        self.assertIn("Not in the current scouting feed.", report)
        self.assertIn("last seen on <b>2019-07-21</b>", report)
        self.assertIn("which is <b>out of date</b>", report)
        self.assertIn("<td>Pace</td><td>8-14</td>", self._section(report, "<h2>Current attributes</h2>"))
        self.assertIn("Historical, last seen 2019-07-21", report)
        # The remembered value is dated, never offered as today's answer.
        self.assertNotIn("<td class='muted'>Now</td>", self._section(report, "<h2>Current attributes</h2>"))

    def test_a_dropped_player_is_not_described_as_never_known(self) -> None:
        port = self._serve_states(dropped_from_reports_player())
        _s, listing = self._get(port, "/scouting?role=af_attack&position=ST")
        _s, report = self._get(port, "/scouting/player/state-dropped")
        row = self._row(listing, "state-dropped")

        self.assertIn("used to be in the scouted pool", row)
        self.assertIn("40% <span class='muted'>(last known)</span>", row)
        # Past knowledge survives: he was known, so he is not "nothing known".
        self.assertIn("<b>1 ranged</b>", row)
        self.assertIn("Last visible 2019-07-21", row)
        self.assertIn("No attributes currently visible", row)
        self.assertNotIn("Not captured from FM", row)

        current = self._section(report, "<h2>Current attributes</h2>")
        self.assertIn("No attributes currently visible.", current)
        self.assertNotIn("Not captured from FM", current)
        past = self._section(report, "<h2>Past scouting knowledge</h2>")
        self.assertIn("Historical only.", past)
        self.assertIn("last visible on <b>2019-07-21</b>", past)
        self.assertIn("not used in any score, filter, or recommendation", past)
        self.assertIn("<td>Pace</td><td>8-14</td>", past)

    def test_user_controlled_text_is_escaped_wherever_it_is_rendered(self) -> None:
        hostile = "<script>alert('x')</script>"
        current = replace(
            current_exact_player(),
            id="state-escape",
            name=f"{hostile} Striker",
            club=hostile,
            nationality=hostile,
            facts={"_note": hostile},
        )
        template = carried_historical_player()
        historical = replace(
            template,
            id="state-escape-history",
            name=f"{hostile} Veteran",
            history=replace(template.history, profile={"club": hostile}),
        )
        escaped = "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
        port = self._serve_states(current, historical)

        _s, listing = self._get(port, "/scouting?view=scouted")
        _s, ever_seen = self._get(port, "/scouting?everScouted=1")
        _s, current_report = self._get(port, "/scouting/player/state-escape")
        _s, history_report = self._get(port, "/scouting/player/state-escape-history")

        for page in (listing, ever_seen, current_report, history_report):
            with self.subTest(page=page[:40]):
                self.assertNotIn("<script>alert", page)
                self.assertIn(escaped, page)
        # The historical club line is built from the profile, then escaped.
        self.assertIn(f"Last seen at {escaped}, {OBSERVED_ON}", ever_seen)
        self.assertIn(f"Last seen at {escaped}, {OBSERVED_ON}", history_report)


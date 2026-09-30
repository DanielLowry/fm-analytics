"""The **Weakest slots** navigation header on ``/scouting``.

The rows come from ``reporting.weakest_slots``; nothing here selects or ranks
a weak slot. What these tests fix down is the link: it must select exactly the
tactic, position and role the row names, keep every other filter the manager
already chose, and stay readable and calm when there is no weak-slot data.
"""

import json
import re
import tempfile
import unittest
from dataclasses import replace
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fm_analytics.analytics import DEFAULT_SORT_BY_MODE
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import WeakSlot, required_role_attributes
from fm_analytics.web.rendering import _scouting_filters
from fm_analytics.web.scouting_render import weakest_slots_panel
from tests.web_support import FIXTURE, WebServerHelpers, write_complete_fixture


def _weak_slot(**overrides) -> WeakSlot:
    """One prepared weak slot, as the reporting layer supplies it."""
    values = dict(
        tactic_key="balanced_442",
        tactic_name="Balanced 4-4-2",
        slot_key="ML",
        position="ML",
        role_key="winger_ml_mr_support",
        role_name="Winger (Support) [ML/MR]",
        role_attributes=(("stamina", 9.0),),
        concern="starter",
        starter_name="Weak Player",
        starter_score=41.5,
        cover_name=None,
        cover_score=None,
        message="Weak Player is a weak link at ML (41 vs XI median 66)",
    )
    values.update(overrides)
    return WeakSlot(**values)


def _first_href(markup: str) -> str:
    match = re.search(r"href='([^']+)'", markup)
    if match is None:
        raise AssertionError("no link was rendered:\n" + markup)
    return unescape(match.group(1))


def _anchor_text(markup: str) -> str:
    match = re.search(r"<a [^>]*>(.*?)</a>", markup)
    if match is None:
        raise AssertionError("no link was rendered:\n" + markup)
    return match.group(1)


def _weak_starter_fixture(directory: Path) -> Path:
    """The complete fixture with one starter well below the rest of the XI."""
    path = write_complete_fixture(directory)
    game, squad = load_fixture(path)
    required = required_role_attributes()
    players = tuple(
        replace(
            player,
            attributes={
                name: AttributeObservation(Visibility.KNOWN, value=1)
                for name in required
            },
        )
        if player.positions == ("ML",)
        else player
        for player in squad.players
    )
    path.write_text(
        json.dumps({"game": game.to_dict(), "squad": replace(squad, players=players).to_dict()}),
        encoding="utf-8",
    )
    return path


class WeakestSlotLinkTests(unittest.TestCase):
    """The link, parsed back through the real scouting filter parser."""

    def test_link_selects_the_slots_tactic_position_and_role(self) -> None:
        panel = weakest_slots_panel([_weak_slot()], {})
        filters = _scouting_filters(parse_qs(urlparse(_first_href(panel)).query))

        self.assertEqual(filters.tactic_key, "balanced_442")
        self.assertEqual(filters.position, "ML")
        self.assertEqual(filters.role_key, "winger_ml_mr_support")

    def test_link_keeps_the_filters_the_slot_does_not_speak_for(self) -> None:
        query = parse_qs(
            "view=scouted&market=free&maxAge=23&minFloor=12&everScouted=1"
            "&fact.nationality=England&name=Somebody&sort=age&dir=asc"
        )
        filters = _scouting_filters(parse_qs(urlparse(_first_href(weakest_slots_panel([_weak_slot()], query))).query))

        self.assertTrue(filters.scouted_only)
        self.assertEqual(filters.market, "free")
        self.assertEqual(filters.maximum_age, 23)
        self.assertEqual(filters.minimum_floor, 12.0)
        self.assertTrue(filters.include_former_scouted)
        self.assertEqual(filters.facts, {"nationality": "England"})

    def test_link_clears_the_name_search_and_the_sort_it_is_leaving(self) -> None:
        query = parse_qs("name=Somebody&sort=age&dir=asc")
        filters = _scouting_filters(parse_qs(urlparse(_first_href(weakest_slots_panel([_weak_slot()], query))).query))

        self.assertIsNone(filters.name_contains)
        # The link decides which table is showing, so the destination table's
        # default sort applies rather than the origin view's column order.
        self.assertEqual(filters.ranking_sort, DEFAULT_SORT_BY_MODE["tactic"])
        self.assertIsNone(filters.ranking_descending)

    def test_every_row_links_to_its_own_slot(self) -> None:
        rows = [
            _weak_slot(slot_key="DCL", position="DC", role_key="cd_defend",
                       role_name="Central Defender (Defend)"),
            _weak_slot(slot_key="GK", position="GK", role_key="gk_defend",
                       role_name="Goalkeeper (Defend)"),
        ]
        panel = weakest_slots_panel(rows, {})

        parsed = [
            _scouting_filters(parse_qs(urlparse(unescape(href)).query))
            for href in re.findall(r"href='([^']+)'", panel)
        ]
        self.assertEqual(
            [(f.tactic_key, f.position, f.role_key) for f in parsed],
            [("balanced_442", "DC", "cd_defend"), ("balanced_442", "GK", "gk_defend")],
        )

    def test_link_text_names_the_slot_without_relying_on_colour(self) -> None:
        panel = weakest_slots_panel([_weak_slot()], {})

        self.assertEqual(
            _anchor_text(panel), "Balanced 4-4-2 · ML · Winger (Support) [ML/MR]"
        )
        self.assertIn("Starter concern:", panel)

    def test_a_slot_whose_key_differs_from_its_position_says_both(self) -> None:
        panel = weakest_slots_panel([_weak_slot(slot_key="DCL", position="DC")], {})

        self.assertIn("Balanced 4-4-2 · DCL (DC) · Winger (Support) [ML/MR]", panel)

    def test_the_concern_is_named_in_words(self) -> None:
        self.assertIn("Cover concern:", weakest_slots_panel([_weak_slot(concern="cover")], {}))
        self.assertIn("Starter concern:", weakest_slots_panel([_weak_slot(concern="starter")], {}))

    def test_names_and_messages_are_escaped(self) -> None:
        panel = weakest_slots_panel(
            [
                _weak_slot(
                    tactic_name="Tiki & Taka <4-4-2>",
                    role_name="Winger (Support) & Inside Forward",
                    message="a <script>alert(1)</script> message",
                )
            ],
            {},
        )

        self.assertIn("Tiki &amp; Taka &lt;4-4-2&gt;", panel)
        self.assertIn("Winger (Support) &amp; Inside Forward", panel)
        self.assertNotIn("<script>", panel)

    def test_no_weak_slots_is_a_calm_sentence_not_a_missing_panel(self) -> None:
        panel = weakest_slots_panel((), {})

        self.assertIn("Weakest slots", panel)
        self.assertIn("No weak slots in the tactics in play right now.", panel)
        self.assertNotIn("fm-risk-list", panel)

    def test_an_unavailable_squad_says_why_and_keeps_the_panel(self) -> None:
        note = "Weakest slots need a complete current squad: nothing is known"
        panel = weakest_slots_panel((), {}, note=note)

        self.assertIn("Weakest slots", panel)
        self.assertIn("nothing is known", panel)
        self.assertNotIn("fm-risk-list", panel)


class WeakestSlotPageTests(WebServerHelpers, unittest.TestCase):
    """The block in its real place on the page, over HTTP."""

    def test_the_header_links_to_the_filtered_candidate_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/scouting")
            self.assertEqual(status, 200)
            self.assertIn("Weakest slots", body)
            href = _first_href(body[body.index("Weakest slots"):])

            destination_status, destination = self._get(port, href)
            # The header is page furniture: the live-filter fragment stays the
            # results half only, so typing must not re-render it.
            fragment_status, fragment = self._get(port, "/scouting/results")

        self.assertEqual(destination_status, 200)
        # The destination shows exactly what the link asked for: the tactic the
        # row belongs to, and the row's own position and role in the form.
        sent = parse_qs(urlparse(href).query)
        self.assertEqual(sent["tactic"], ["balanced_442"])
        self.assertIn("value='balanced_442' selected", destination)
        self.assertIn(f"value='{sent['position'][0]}' selected", destination)
        self.assertIn(f"value='{sent['role'][0]}' selected", destination)
        self.assertEqual(fragment_status, 200)
        self.assertNotIn("Weakest slots", fragment)

    def test_a_weak_starter_is_named_as_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _weak_starter_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/scouting")

        self.assertEqual(status, 200)
        self.assertIn("Starter concern:", body)
        self.assertIn("Cover concern:", body)
        self.assertLess(body.index("Starter concern:"), body.index("Cover concern:"))

    def test_an_incomplete_squad_keeps_a_calm_empty_state(self) -> None:
        port = self._serve(FIXTURE)

        status, body = self._get(port, "/scouting")

        self.assertEqual(status, 200)
        self.assertIn("Weakest slots", body)
        self.assertIn("need a complete current squad", body)
        self.assertNotIn("fm-risk-list", body)


if __name__ == "__main__":
    unittest.main()

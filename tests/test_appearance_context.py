import unittest
from dataclasses import dataclass
from datetime import date

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.appearance_context import (
    CONFIRMED,
    DOES_NOT_FIT,
    DUTY_UNSETTLED,
    FRIENDLY,
    INFERRED,
    MOVED,
    NEW_SHAPE,
    NO_PLAYER_ID,
    NO_POSITION,
    NO_RATING,
    NO_TACTIC,
    UNCONFIRMED_ROLE,
    UNCONFIRMED_TACTIC,
    appearance_contexts,
    summarise_coverage,
)
from fm_analytics.analytics.match_roles import RoleCodes, role_family
from fm_analytics.domain.matches import MatchCapture

from tests.match_support import FRIENDLY as FRIENDLY_COMPETITION
from tests.match_support import US, capture_document, player, season

DETAILED = "2019-09-01:100:201"
# Where FM lists our Vertical 4-4-2: right before left, as its line-up does.
PLACES = (("GK", None), ("DR", None), ("DC", "right"), ("DC", "left"), ("DL", None), ("MR", None),
          ("MC", "right"), ("MC", "left"), ("ML", None), ("ST", "right"), ("ST", "left"))


@dataclass(frozen=True)
class Note:
    tactic_key: str | None = None


def placed(matches, side="home"):
    """The detailed match's players with FM's positions and squad IDs, as a capture now records them."""
    detail = matches[-1]["detail"]
    for line, (position, centre) in zip((p for p in detail["players"] if p["side"] == side), PLACES):
        line.update({"position": position, "startPosition": position, "startCentreSide": centre,
                     "playerId": str(line["shortId"])})
    return matches


def substitute(order, code, position, came_on, replaced_order, *, went_off_position=None, matches):
    """Take a home starter off at `came_on` and bring a substitute on at `position`."""
    players = matches[-1]["detail"]["players"]
    players[replaced_order]["wentOff"] = came_on
    if went_off_position:
        players[replaced_order]["position"] = went_off_position
    line = player("home", order, code, came_on=came_on)
    line.update({"position": position, "playerId": str(line["shortId"])})
    players.append(line)
    return matches


def contexts(matches, notes=None, confirmed=None):
    records = MatchCapture.from_document(capture_document(matches)).matches
    codes = RoleCodes.build(MVP_CATALOGUE, confirmed or {})
    return appearance_contexts(records, US["id"], notes=notes or {}, codes=codes)


def detailed(found):
    return {c.player.order: c for c in found if c.match.key == DETAILED}


class RoleFamilyTests(unittest.TestCase):
    def test_a_family_is_the_role_without_its_duty(self) -> None:
        self.assertEqual(role_family(MVP_CATALOGUE, "cm_defend"), "Central Midfielder")
        self.assertEqual(role_family(MVP_CATALOGUE, "cm_support"), "Central Midfielder")
        self.assertEqual(role_family(MVP_CATALOGUE, "winger_ml_mr_support"), "Winger [ML/MR]")

    def test_every_catalogue_role_has_a_family(self) -> None:
        for key in MVP_CATALOGUE.roles:
            self.assertTrue(role_family(MVP_CATALOGUE, key))


class ContextTests(unittest.TestCase):
    def test_a_confirmed_tactic_settles_each_starters_job(self) -> None:
        by_order = detailed(contexts(placed(season()), notes={DETAILED: Note("vertical_442")}))
        self.assertEqual(by_order[0].tactic_source, CONFIRMED)
        jobs = {order: (c.position, c.role_key) for order, c in by_order.items() if c.usable}
        self.assertEqual(jobs, {
            0: ("GK", "gk_defend"), 1: ("DR", "fb_support"), 4: ("DL", "fb_support"),
            5: ("MR", "winger_ml_mr_support"), 6: ("MC", "b2b_support"), 7: ("MC", "cm_defend"),
            8: ("ML", "winger_ml_mr_support"), 9: ("ST", "pf_support"), 10: ("ST", "af_attack"),
        })

    def test_the_catalogues_mirrored_strikers_still_resolve_by_role(self) -> None:
        # FM: Pressing Forward right, Advanced Forward left; the catalogue has them the other way.
        by_order = detailed(contexts(placed(season()), notes={DETAILED: Note("vertical_442")}))
        self.assertEqual((by_order[9].slot_key, by_order[10].slot_key), ("STL", "STR"))

    def test_a_duty_the_tactic_leaves_open_is_not_guessed(self) -> None:
        # Either Vertical 4-4-2 centre-back may play Cover, and the code has no duty.
        by_order = detailed(contexts(placed(season()), notes={DETAILED: Note("vertical_442")}))
        for order in (2, 3):
            self.assertIsNone(by_order[order].role_key)
            self.assertEqual(by_order[order].exclusions, (DUTY_UNSETTLED,))

    def test_one_code_for_two_duties_is_told_apart_by_the_slot(self) -> None:
        # 28 March 2020: Central Midfielder (Support) right of Central Midfielder (Defend), both 0x20.
        matches = placed(season())
        matches[-1]["detail"]["players"][6]["roleCode"] = 0x20
        by_order = detailed(contexts(matches, notes={DETAILED: Note("vertical_442")}))
        self.assertEqual((by_order[6].slot_key, by_order[6].role_key), ("MCR", "cm_support"))
        self.assertEqual((by_order[7].slot_key, by_order[7].role_key), ("MCL", "cm_defend"))

    def test_an_inferred_tactic_waits_for_confirmation(self) -> None:
        by_order = detailed(contexts(placed(season())))
        self.assertEqual((by_order[0].tactic_key, by_order[0].tactic_source), ("vertical_442", INFERRED))
        self.assertTrue(by_order[0].awaits_tactic_confirmation)
        self.assertEqual(by_order[0].exclusions, (UNCONFIRMED_TACTIC,))
        self.assertEqual(by_order[2].exclusions, (DUTY_UNSETTLED, UNCONFIRMED_TACTIC))

    def test_a_substitute_takes_the_slot_of_the_player_he_replaced(self) -> None:
        matches = substitute(11, 0x20, "MC", 63, 7, matches=placed(season()))
        sub = detailed(contexts(matches, notes={DETAILED: Note("vertical_442")}))[11]
        self.assertEqual((sub.slot_key, sub.role_key, sub.exclusions), ("MCL", "cm_defend", ()))

    def test_a_substitute_into_a_new_shape_is_not_used(self) -> None:
        # A winger off, a Box-to-Box Midfielder on in central midfield.
        matches = substitute(11, 0x10000, "MC", 67, 5, matches=placed(season()))
        sub = detailed(contexts(matches, notes={DETAILED: Note("vertical_442")}))[11]
        self.assertEqual(sub.exclusions, (NEW_SHAPE,))

    def test_a_role_that_does_not_fit_the_position_in_the_tactic_is_not_used(self) -> None:
        # A Full-Back code on at centre-back, for a centre-back.
        matches = substitute(11, 0x4, "DC", 77, 3, matches=placed(season()))
        sub = detailed(contexts(matches, notes={DETAILED: Note("vertical_442")}))[11]
        self.assertEqual(sub.exclusions, (DOES_NOT_FIT,))

    def test_a_starter_who_moved_did_two_jobs(self) -> None:
        matches = placed(season())
        matches[-1]["detail"]["players"][8]["position"] = "MC"
        moved = detailed(contexts(matches, notes={DETAILED: Note("vertical_442")}))[8]
        self.assertIn(MOVED, moved.exclusions)

    def test_what_cannot_be_established_is_named(self) -> None:
        matches = placed(season())
        lines = matches[-1]["detail"]["players"]
        lines[0]["playerId"] = None
        lines[1]["rating"] = None
        lines[4]["roleCode"] = 0x40000
        by_order = detailed(contexts(matches, notes={DETAILED: Note("vertical_442")}))
        self.assertIn(NO_PLAYER_ID, by_order[0].exclusions)
        self.assertIn(NO_RATING, by_order[1].exclusions)
        self.assertIn(UNCONFIRMED_ROLE, by_order[4].exclusions)

    def test_a_capture_without_positions_has_no_usable_appearance(self) -> None:
        matches = season()
        for line in matches[-1]["detail"]["players"]:
            line["playerId"] = str(line["shortId"])
        by_order = detailed(contexts(matches, notes={DETAILED: Note("vertical_442")}))
        self.assertTrue(all(NO_POSITION in c.exclusions for c in by_order.values()))

    def test_friendlies_and_unknown_tactics_are_named(self) -> None:
        matches = placed(season())
        matches[-1]["competition"] = FRIENDLY_COMPETITION
        lines = matches[-1]["detail"]["players"]
        lines[10]["roleCode"] = 0x40000  # no tactic can be inferred with an unknown code
        by_order = detailed(contexts(matches))
        self.assertEqual(by_order[0].exclusions, (FRIENDLY, NO_TACTIC))
        self.assertIsNone(by_order[0].tactic_source)


class CoverageTests(unittest.TestCase):
    def test_the_report_counts_what_is_usable_waiting_or_excluded(self) -> None:
        found = contexts(placed(season()))
        coverage = summarise_coverage(found, since=date(2019, 8, 31), until=date(2019, 9, 5))
        self.assertEqual((coverage.matches, len(coverage.appearances)), (1, 11))
        self.assertEqual((len(coverage.usable), len(coverage.awaiting_tactic), len(coverage.excluded)), (0, 9, 2))
        self.assertEqual(coverage.reasons(), [(DUTY_UNSETTLED, 2), (UNCONFIRMED_TACTIC, 2)])
        self.assertEqual(coverage.unsettled_duties(), [("vertical_442", "DC", "Central Defender", 2)])
        (to_confirm,) = coverage.matches_to_confirm()
        self.assertEqual((to_confirm.match.key, to_confirm.tactic_key, to_confirm.appearances), (DETAILED, "vertical_442", 9))
        jobs = {(job.position, job.role_key): (job.usable, job.awaiting) for job in coverage.jobs()}
        self.assertEqual(jobs[("ST", "af_attack")], (0, 1))
        self.assertEqual(jobs[("DR", "fb_support")], (0, 1))

    def test_confirming_the_tactic_makes_the_waiting_appearances_usable(self) -> None:
        found = contexts(placed(season()), notes={DETAILED: Note("vertical_442")})
        coverage = summarise_coverage(found, since=None, until=None)
        self.assertEqual((len(coverage.usable), len(coverage.awaiting_tactic)), (9, 0))
        self.assertEqual(coverage.matches_to_confirm(), ())

    def test_the_window_keeps_matches_after_since_up_to_until(self) -> None:
        found = contexts(placed(season()))
        self.assertEqual(summarise_coverage(found, since=date(2019, 9, 1), until=None).appearances, ())
        self.assertEqual(summarise_coverage(found, since=None, until=date(2019, 8, 31)).appearances, ())


if __name__ == "__main__":
    unittest.main()

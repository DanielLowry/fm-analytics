"""The tactic page's grouped FM settings: linked instructions always sit together.

The layouts themselves are data (`GROUPS` in each phase's render module); these
tests hold every phase to showing each setting exactly once, with every pair of
instructions that lock each other in one row, so the page can never again split
Work Ball Into Box from the Hit Early Crosses that makes it unavailable.
"""

import re
import unittest
from collections import Counter

from fm_analytics.analytics import MVP_CATALOGUE, InPossessionSettings
from fm_analytics.analytics.in_possession import (
    FIXED_TOGGLES,
    IN_POSSESSION_CLASHES,
    PLAYER_DEPENDENT_TOGGLES,
)
from fm_analytics.analytics.in_transition import IN_TRANSITION_CLASHES, SECTIONS
from fm_analytics.analytics.out_of_possession import FIELD_LABELS
from fm_analytics.web import in_possession_render, in_transition_render, out_of_possession_render
from fm_analytics.web.instruction_controls import (
    Flag,
    Scale,
    Toggles,
    clash_rule,
    instruction_legend,
    toggle_rows,
)

IN_POSSESSION_SCALES = {"attacking_width", "passing_directness", "tempo", "time_wasting", "crossing_type"}


def _scales(groups) -> list[str]:
    return [row.attribute for group in groups for row in group.rows if isinstance(row, (Scale, Flag))]


def _row_with(html: str, name: str) -> str:
    """The toggle row on a rendered page that shows `name`."""
    for row in re.findall(r"<div class='fm-toggle-row'>.*?</div>", html):
        if f"<span>{name}</span>" in row:
            return row
    raise AssertionError(f"no toggle row shows {name!r}")


class LayoutCoversEverySettingOnceTests(unittest.TestCase):
    def assert_linked_toggles_share_a_row(self, groups, toggles, clashes) -> None:
        shown = Counter(name for row in toggle_rows(groups) for name in row.names)
        self.assertEqual(set(shown), set(toggles))
        self.assertEqual({count for count in shown.values()}, {1})
        for first, second in clashes:
            with self.subTest(first=first, second=second):
                self.assertTrue(any({first, second} <= set(row.names) for row in toggle_rows(groups)))

    def test_in_possession(self) -> None:
        self.assert_linked_toggles_share_a_row(
            in_possession_render.GROUPS, FIXED_TOGGLES + PLAYER_DEPENDENT_TOGGLES, IN_POSSESSION_CLASHES
        )
        scales = _scales(in_possession_render.GROUPS)
        self.assertEqual(sorted(scales), sorted(IN_POSSESSION_SCALES))

    def test_in_transition(self) -> None:
        every_choice = tuple(name for _attribute, _key, _label, options in SECTIONS for name in options)
        self.assert_linked_toggles_share_a_row(in_transition_render.GROUPS, every_choice, IN_TRANSITION_CLASHES)

    def test_out_of_possession(self) -> None:
        scales = _scales(out_of_possession_render.GROUPS)
        self.assertEqual(sorted(scales), sorted(attribute for attribute, _label in FIELD_LABELS))
        self.assertEqual(toggle_rows(out_of_possession_render.GROUPS), ())


class ClashRuleTests(unittest.TestCase):
    def test_one_instruction_that_locks_the_rest_is_named(self) -> None:
        row = Toggles(("Work Ball Into Box", "Hit Early Crosses", "Shoot On Sight"))
        self.assertEqual(
            clash_rule(row, IN_POSSESSION_CLASHES),
            "Work ball into box rules out hit early crosses and shoot on sight. "
            "Hit early crosses and shoot on sight can be selected together.",
        )

    def test_a_pair_and_a_larger_exclusive_set(self) -> None:
        self.assertEqual(clash_rule(Toggles(("Dribble Less", "Run At Defence")), IN_POSSESSION_CLASHES),
                         "Pick one or neither.")
        types = in_transition_render.GROUPS[1].rows[2]
        self.assertEqual(clash_rule(types, IN_TRANSITION_CLASHES), "Pick one at most.")

    def test_an_exception_to_one_at_most_is_spelled_out(self) -> None:
        targets = in_transition_render.GROUPS[1].rows[1]
        self.assertEqual(
            clash_rule(targets, IN_TRANSITION_CLASHES),
            "Pick one at most, except that centre backs and full backs can be selected together.",
        )

    def test_unlinked_toggles_have_no_rule(self) -> None:
        self.assertEqual(clash_rule(Toggles(("Play Out Of Defence", "Pass Into Space")), IN_POSSESSION_CLASHES), "")


class RenderedPageTests(unittest.TestCase):
    def test_work_ball_into_box_sits_with_the_early_crosses_that_lock_it(self) -> None:
        tactic = MVP_CATALOGUE.tactics["vertical_442"]
        self.assertIn("Hit Early Crosses", tactic.in_possession.player_selected)
        row = _row_with(in_possession_render.in_possession_section(tactic), "Work ball into box")
        self.assertIn("<span>Hit early crosses</span><b>Selected</b>", row)
        self.assertIn("title='Unavailable: Hit Early Crosses is selected'", row)
        self.assertIn("<span>Shoot on sight</span><b>Not selected</b>", row)
        self.assertIn("Work ball into box rules out hit early crosses and shoot on sight.", row)
        # Fixed and player-dependent toggles share the row; only the latter are marked.
        self.assertEqual(row.count("class='fm-depends'"), 2)

    def test_a_row_that_all_depends_on_players_says_so_once(self) -> None:
        tactic = MVP_CATALOGUE.tactics["vertical_442"]
        row = _row_with(in_possession_render.in_possession_section(tactic), "Dribble less")
        self.assertEqual(row.count("class='fm-depends'"), 1)
        self.assertRegex(row, "<span class='fm-toggles-label'>Dribbling<span class='fm-depends'")

    def test_unauthored_toggles_are_not_set_and_player_fallbacks_are_not_selected(self) -> None:
        tactic = MVP_CATALOGUE.tactics["lowblock_442"]
        self.assertIsNone(tactic.in_possession)
        section = in_possession_render.in_possession_section(tactic)
        self.assertEqual(section.count("<b>Not set</b>"), len(FIXED_TOGGLES) + 3)
        self.assertEqual(
            section.count("<b>Not selected</b>"),
            len(PLAYER_DEPENDENT_TOGGLES) - len(InPossessionSettings().player_selected),
        )
        self.assertIn("Not yet set:", section)

    def test_a_scale_marks_where_its_value_sits(self) -> None:
        section = out_of_possession_render.out_of_possession_section(MVP_CATALOGUE.tactics["vertical_442"])
        line = section.split("<span>Defensive line</span>", 1)[1].split("</ol>", 1)[0]
        self.assertEqual(
            re.findall(r"<li( class='is-on')? title='([^']+)'>", line),
            [("", "Much Lower"), ("", "Lower"), (" class='is-on'", "Standard"), ("", "Higher"), ("", "Much Higher")],
        )

    def test_the_legend_explains_every_state(self) -> None:
        legend = instruction_legend()
        for text in ("Selected", "Not selected (FM&#x27;s default)", "Unavailable", "Not set for this tactic yet",
                     "Depends on players", "Depends on the score"):
            self.assertIn(text, legend)


if __name__ == "__main__":
    unittest.main()

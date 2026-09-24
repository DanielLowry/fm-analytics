"""Per-tactic attribute emphasis: a tactic shifts what it asks of its players.

Emphasis is a *delta* on each role's own weight. A role that does not already
weight the attribute starts at zero, so tactics can add contextual requirements.
"""

import unittest
from dataclasses import replace

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    PlayerSelectionInput,
    evaluate_tactic,
)
from fm_analytics.analytics.catalogue import (
    MAX_EFFECTIVE_WEIGHT,
    AttributeEmphasis,
    FootballCatalogue,
)
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes

TACTIC = "balanced_442"


def with_emphasis(emphasis, tactic_key: str = TACTIC) -> FootballCatalogue:
    """A catalogue whose tactic has this emphasis.

    A plain dict is one whole-team block; otherwise pass a list of blocks.
    """
    if isinstance(emphasis, dict):
        emphasis = [AttributeEmphasis(emphasis)] if emphasis else []
    # The fixture tests emphasis in isolation. Shipped tactics now also carry
    # attribute tapers, whose deliberate player-selection penalty would obscure
    # whether an emphasis block itself changed the choice.
    tactic = replace(
        MVP_CATALOGUE.tactics[tactic_key],
        attribute_emphasis=tuple(emphasis),
        attribute_taper=(),
    )
    return replace(MVP_CATALOGUE, tactics={**MVP_CATALOGUE.tactics, tactic_key: tactic})


def slot_weights(catalogue: FootballCatalogue, slot_key: str) -> dict[str, float]:
    """The weights the tactic applies to whoever fills `slot_key`, in its default role."""
    view = catalogue.for_tactic(TACTIC)
    slot = next(s for s in view.tactics[TACTIC].slots if s.key == slot_key)
    return {a.name: a.weight for a in view.role_for_slot(slot, slot.role_key).attributes}


def base_slot_weights(slot_key: str) -> dict[str, float]:
    slot = next(s for s in MVP_CATALOGUE.tactics[TACTIC].slots if s.key == slot_key)
    return {a.name: a.weight for a in MVP_CATALOGUE.roles[slot.role_key].attributes}


def weights(catalogue: FootballCatalogue, role_key: str) -> dict[str, float]:
    return {a.name: a.weight for a in catalogue.roles[role_key].attributes}


class DerivedCatalogueTests(unittest.TestCase):
    def test_a_tactic_with_no_emphasis_or_taper_returns_the_same_catalogue(self) -> None:
        bare = with_emphasis({})
        self.assertIs(bare.for_tactic(TACTIC), bare)

    def test_emphasis_shifts_the_weight_where_the_role_has_the_attribute(self) -> None:
        base = weights(MVP_CATALOGUE, "b2b_support")["passing"]
        derived = with_emphasis({"passing": 2}).for_tactic(TACTIC)
        self.assertEqual(weights(derived, "b2b_support")["passing"], base + 2)

    def test_a_negative_emphasis_lowers_the_weight(self) -> None:
        base = weights(MVP_CATALOGUE, "b2b_support")["passing"]
        derived = with_emphasis({"passing": -2}).for_tactic(TACTIC)
        self.assertEqual(weights(derived, "b2b_support")["passing"], base - 2)

    def test_positive_emphasis_can_introduce_an_attribute(self) -> None:
        self.assertNotIn("stamina", weights(MVP_CATALOGUE, "cd_defend"))
        derived = with_emphasis({"stamina": 2}).for_tactic(TACTIC)
        self.assertEqual(weights(derived, "cd_defend")["stamina"], 2)

    def test_weights_are_clamped_to_the_scale(self) -> None:
        high = with_emphasis({"passing": MAX_EFFECTIVE_WEIGHT}).for_tactic(TACTIC)
        self.assertEqual(weights(high, "b2b_support")["passing"], MAX_EFFECTIVE_WEIGHT)
        low = with_emphasis({"passing": -MAX_EFFECTIVE_WEIGHT}).for_tactic(TACTIC)
        self.assertNotIn("passing", weights(low, "b2b_support"))

    def test_identity_of_every_role_survives_derivation(self) -> None:
        derived = with_emphasis({"passing": 2, "stamina": 2}).for_tactic(TACTIC)
        self.assertEqual(derived.version, MVP_CATALOGUE.version)
        self.assertEqual(set(derived.roles), set(MVP_CATALOGUE.roles))
        for key, role in MVP_CATALOGUE.roles.items():
            self.assertEqual(derived.roles[key].key, role.key)
            self.assertEqual(derived.roles[key].name, role.name)
            self.assertEqual(derived.roles[key].eligible_positions, role.eligible_positions)
            self.assertEqual(derived.roles[key].system_traits, role.system_traits)

    def test_the_derived_catalogue_is_memoised(self) -> None:
        catalogue = with_emphasis({"passing": 2})
        self.assertIs(catalogue.for_tactic(TACTIC), catalogue.for_tactic(TACTIC))

    def test_a_slot_block_adds_to_the_tactic_block_for_that_slot_only(self) -> None:
        tactic = MVP_CATALOGUE.tactics[TACTIC]
        slots = list(tactic.slots)
        slots[6] = replace(slots[6], attribute_emphasis={"passing": 2})
        changed = replace(
            tactic, slots=tuple(slots), attribute_emphasis=(AttributeEmphasis({"passing": 1}),)
        )
        catalogue = replace(MVP_CATALOGUE, tactics={**MVP_CATALOGUE.tactics, TACTIC: changed})
        derived = catalogue.for_tactic(TACTIC)
        singled = derived.role_for_slot(slots[6], slots[6].role_key)
        other = derived.role_for_slot(slots[7], slots[7].role_key)
        # Slot 6 gets the tactic-wide +1 and its own +2; everyone else just +1.
        clamp = lambda value: min(MAX_EFFECTIVE_WEIGHT, value)
        self.assertEqual(
            {a.name: a.weight for a in singled.attributes}["passing"],
            clamp(weights(MVP_CATALOGUE, slots[6].role_key)["passing"] + 3),
        )
        self.assertEqual(
            {a.name: a.weight for a in other.attributes}["passing"],
            clamp(weights(MVP_CATALOGUE, slots[7].role_key)["passing"] + 1),
        )


class PositionBlockTests(unittest.TestCase):
    """A block with `positions` reaches only the slots at those positions."""

    BACK_LINE = ("DL", "DC", "DR")

    def test_a_position_block_reaches_only_those_positions(self) -> None:
        catalogue = with_emphasis([AttributeEmphasis({"pace": 2}, self.BACK_LINE)])
        # DCL is a centre-back: pace moves. MCL is a midfielder: it does not.
        self.assertEqual(
            slot_weights(catalogue, "DCL")["pace"], base_slot_weights("DCL")["pace"] + 2
        )
        self.assertEqual(slot_weights(catalogue, "MCL"), base_slot_weights("MCL"))

    def test_a_position_block_reaches_every_slot_at_that_position(self) -> None:
        catalogue = with_emphasis([AttributeEmphasis({"pace": 2}, ("DC",))])
        for slot_key in ("DCL", "DCR"):
            self.assertEqual(
                slot_weights(catalogue, slot_key)["pace"],
                base_slot_weights(slot_key)["pace"] + 2, slot_key,
            )

    def test_overlapping_blocks_add_up(self) -> None:
        catalogue = with_emphasis([
            AttributeEmphasis({"pace": 1}),                      # whole team
            AttributeEmphasis({"pace": 2}, ("DC",)),             # centre-backs
        ])
        self.assertEqual(
            slot_weights(catalogue, "DCL")["pace"], base_slot_weights("DCL")["pace"] + 3
        )

    def test_a_whole_team_block_still_reaches_slots_a_position_block_skips(self) -> None:
        catalogue = with_emphasis([
            AttributeEmphasis({"passing": 1}),
            AttributeEmphasis({"passing": 2}, ("DC",)),
        ])
        # MCL is not a centre-back, so it gets the whole-team +1 and nothing more.
        self.assertEqual(
            slot_weights(catalogue, "MCL")["passing"],
            min(MAX_EFFECTIVE_WEIGHT, base_slot_weights("MCL")["passing"] + 1),
        )

    def test_opposite_deltas_cancel_before_clamping(self) -> None:
        catalogue = with_emphasis([
            AttributeEmphasis({"pace": 4}), AttributeEmphasis({"pace": -4}, ("DC",)),
        ])
        self.assertEqual(slot_weights(catalogue, "DCL"), base_slot_weights("DCL"))

    def test_block_order_does_not_matter(self) -> None:
        a = AttributeEmphasis({"pace": 1})
        b = AttributeEmphasis({"pace": 2}, ("DC",))
        self.assertEqual(
            slot_weights(with_emphasis([a, b]), "DCL"), slot_weights(with_emphasis([b, a]), "DCL")
        )

    def test_a_position_block_can_add_a_new_requirement(self) -> None:
        self.assertNotIn("stamina", base_slot_weights("DCL"))
        catalogue = with_emphasis([AttributeEmphasis({"stamina": 2}, ("DC",))])
        self.assertEqual(slot_weights(catalogue, "DCL")["stamina"], 2)

    def test_a_broad_block_reaches_roles_without_a_base_weight(self) -> None:
        catalogue = with_emphasis({"stamina": 2})
        self.assertEqual(slot_weights(catalogue, "DCL")["stamina"], 2)
        self.assertGreater(
            slot_weights(catalogue, "MCL")["stamina"],
            base_slot_weights("MCL")["stamina"],
        )

    def test_a_slot_block_can_add_a_new_requirement(self) -> None:
        tactic = MVP_CATALOGUE.tactics[TACTIC]
        slots = list(tactic.slots)
        slots[2] = replace(slots[2], attribute_emphasis={"stamina": 2})
        changed = replace(tactic, slots=tuple(slots), attribute_emphasis=())
        catalogue = replace(MVP_CATALOGUE, tactics={**MVP_CATALOGUE.tactics, TACTIC: changed})
        self.assertEqual(slot_weights(catalogue, slots[2].key)["stamina"], 2)

    def test_a_tactic_with_only_position_blocks_still_leaves_other_slots_alone(self) -> None:
        catalogue = with_emphasis([AttributeEmphasis({"pace": 2}, self.BACK_LINE)])
        view = catalogue.for_tactic(TACTIC)
        # Nothing whole-team, so the plain role table is untouched.
        self.assertEqual(weights(view, "b2b_support"), weights(MVP_CATALOGUE, "b2b_support"))

    def test_a_position_the_tactic_does_not_field_is_refused(self) -> None:
        # balanced_442 has no wing-backs; a block naming them would do nothing.
        with self.assertRaisesRegex(ValueError, "does not field"):
            with_emphasis([AttributeEmphasis({"pace": 2}, ("WBL",))])

    def test_a_typo_in_a_position_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not field"):
            with_emphasis([AttributeEmphasis({"pace": 2}, ("DCL",))])   # slot key, not position

    def test_positions_must_be_unique(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            AttributeEmphasis({"pace": 2}, ("DC", "DC"))

    def test_an_empty_block_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one attribute"):
            AttributeEmphasis({})

    def test_a_position_block_changes_who_is_picked_at_that_position_only(self) -> None:
        # Emphasising crossing for wide midfielders decides the ML pick, and
        # leaves the (identical) MR and every other slot exactly as it was.
        players = SelectionEffectTests()._players()
        plain = evaluate_tactic(MVP_CATALOGUE.tactics[TACTIC], players, MVP_CATALOGUE)
        boosted = with_emphasis([AttributeEmphasis({"tackling": 7}, ("ML",))])
        after = evaluate_tactic(boosted.tactics[TACTIC], players, boosted)
        picked = lambda ev, key: next(a.player_name for a in ev.assignments if a.slot.key == key)
        self.assertEqual(picked(plain, "ML"), "Crosser")
        self.assertEqual(picked(after, "ML"), "Tackler")


class LoadingTests(unittest.TestCase):
    def test_the_old_dict_form_is_refused_with_a_message_that_says_what_to_write(self) -> None:
        from fm_analytics.analytics.catalogue import _emphasis_blocks

        with self.assertRaisesRegex(ValueError, "list of blocks"):
            _emphasis_blocks({"stamina": 2}, "t")

    def test_blocks_load_with_and_without_positions(self) -> None:
        from fm_analytics.analytics.catalogue import _emphasis_blocks

        blocks = _emphasis_blocks(
            [{"attributes": {"stamina": 2}}, {"attributes": {"pace": 2}, "positions": ["DC", "DL"]}],
            "t",
        )
        self.assertEqual(blocks[0].positions, ())
        self.assertEqual(blocks[1].positions, ("DC", "DL"))
        self.assertTrue(blocks[0].applies_to("ST"))
        self.assertTrue(blocks[1].applies_to("DC"))
        self.assertFalse(blocks[1].applies_to("ST"))

    def test_a_misspelled_block_key_is_refused(self) -> None:
        from fm_analytics.analytics.catalogue import _emphasis_blocks

        # "position" for "positions" would otherwise silently make a whole-team block.
        with self.assertRaisesRegex(ValueError, "may only have"):
            _emphasis_blocks([{"attributes": {"pace": 2}, "position": ["DC"]}], "t")


class ValidationTests(unittest.TestCase):
    def test_an_unknown_attribute_is_refused(self) -> None:
        # A typo would weight nothing and say nothing.
        with self.assertRaisesRegex(ValueError, "unknown attributes"):
            with_emphasis({"stamna": 2})

    def test_a_non_integer_delta_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            with_emphasis({"passing": 1.5})

    def test_an_out_of_range_delta_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be between"):
            with_emphasis({"passing": 99})


class SelectionEffectTests(unittest.TestCase):
    """Emphasis must actually change who is picked, not just the number."""

    def _players(self) -> tuple[PlayerSelectionInput, ...]:
        """Ten all-rounders who cannot play ML, plus two who can and differ.

        Keeping the rivals the only ML-eligible players isolates the question:
        with everything else equal, does the tactic's emphasis decide which of
        them takes the slot?
        """
        attributes = sorted(required_role_attributes())
        players = [
            PlayerSelectionInput(
                id=f"base-{index}", name=f"Base {index}",
                positions=("GK", "DL", "DR", "DC", "MC", "MR", "ST"),
                attributes={
                    name: AttributeObservation(Visibility.KNOWN, value=12)
                    for name in attributes
                },
                availability="available", injured=False, suspended=False,
                condition_percent=100, match_fitness_percent=100,
            )
            for index in range(12)
        ]
        for name, strong, weak in (
            ("Crosser", "crossing", "tackling"), ("Tackler", "tackling", "crossing"),
        ):
            values = {n: AttributeObservation(Visibility.KNOWN, value=12) for n in attributes}
            values[strong] = AttributeObservation(Visibility.KNOWN, value=20)
            values[weak] = AttributeObservation(Visibility.KNOWN, value=4)
            players.append(PlayerSelectionInput(
                id=name, name=name, positions=("ML",), attributes=values,
                availability="available", injured=False, suspended=False,
                condition_percent=100, match_fitness_percent=100,
            ))
        return tuple(players)

    def _winger(self, catalogue: FootballCatalogue) -> str:
        evaluation = evaluate_tactic(catalogue.tactics[TACTIC], self._players(), catalogue)
        return next(a.player_name for a in evaluation.assignments if a.slot.key == "ML")

    def test_emphasising_an_attribute_changes_who_fills_the_slot(self) -> None:
        # The deltas are not symmetric because the role is not: a winger starts
        # at crossing 9 and tackling 3, so preferring the tackler takes a bigger
        # nudge than confirming the crosser does.
        self.assertEqual(self._winger(with_emphasis({"crossing": 2})), "Crosser")
        self.assertEqual(self._winger(with_emphasis({"tackling": 7})), "Tackler")

    def test_a_soft_nudge_does_not_overturn_a_large_role_preference(self) -> None:
        # +2 is the seeded band. It must be able to separate close candidates
        # without being able to reverse what the role fundamentally asks for.
        self.assertEqual(self._winger(with_emphasis({"tackling": 2})), "Crosser")


class ShippedSeedTests(unittest.TestCase):
    """The committed emphasis stays inside the soft band it was measured at."""

    SEED_DELTA = 2

    def test_every_tactic_declares_an_emphasis(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertTrue(tactic.attribute_emphasis, tactic.key)

    def test_no_delta_exceeds_the_soft_band(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            for block in tactic.attribute_emphasis:
                for attribute, delta in block.attributes.items():
                    self.assertLessEqual(
                        abs(delta), self.SEED_DELTA, f"{tactic.key}: {attribute} {delta:+d}"
                    )

    def test_no_slot_level_emphasis_is_seeded(self) -> None:
        # Slot-level emphasis is reserved for deliberate hand tuning.
        for tactic in MVP_CATALOGUE.tactics.values():
            for slot in tactic.slots:
                self.assertEqual(slot.attribute_emphasis, {}, f"{tactic.key}/{slot.key}")

    def test_pressing_wide_midfielders_gain_the_authored_aggression_requirement(self) -> None:
        catalogue = MVP_CATALOGUE.for_tactic("pressing_442")
        tactic = catalogue.tactics["pressing_442"]
        for slot in (slot for slot in tactic.slots if slot.position in {"ML", "MR"}):
            role = catalogue.role_for_slot(slot, slot.role_key)
            role_weights = {attribute.name: attribute.weight for attribute in role.attributes}
            self.assertEqual(role_weights["aggression"], 1, slot.key)

    def test_tactics_do_not_all_emphasise_the_same_attributes(self) -> None:
        # Emphasis exists to separate tactics; identical blocks everywhere would
        # be a weighting that says nothing.
        blocks = {frozenset(t.emphasised_attributes) for t in MVP_CATALOGUE.tactics.values()}
        self.assertGreaterEqual(len(blocks), len(MVP_CATALOGUE.tactics) // 3)

    def test_emphasised_attributes_lists_whole_team_first_without_repeats(self) -> None:
        tactic = replace(
            MVP_CATALOGUE.tactics[TACTIC],
            attribute_emphasis=(
                AttributeEmphasis({"pace": 2}, ("DC",)),
                AttributeEmphasis({"stamina": 2, "pace": 1}),
            ),
        )
        self.assertEqual(tactic.emphasised_attributes, ("stamina", "pace"))


if __name__ == "__main__":
    unittest.main()

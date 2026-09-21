"""Per-tactic attribute emphasis: a tactic shifts what it asks of its players.

Emphasis is a *delta* on each role's own weight, applied only where the role
already weights the attribute, so a tactic tunes what a role cares about and
never invents a new requirement for it.
"""

import unittest
from dataclasses import replace

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    PlayerSelectionInput,
    evaluate_tactic,
)
from fm_analytics.analytics.catalogue import MAX_EFFECTIVE_WEIGHT, FootballCatalogue
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes

TACTIC = "balanced_442"


def with_emphasis(emphasis: dict[str, int], tactic_key: str = TACTIC) -> FootballCatalogue:
    tactic = replace(MVP_CATALOGUE.tactics[tactic_key], attribute_emphasis=emphasis)
    return replace(MVP_CATALOGUE, tactics={**MVP_CATALOGUE.tactics, tactic_key: tactic})


def weights(catalogue: FootballCatalogue, role_key: str) -> dict[str, float]:
    return {a.name: a.weight for a in catalogue.roles[role_key].attributes}


class DerivedCatalogueTests(unittest.TestCase):
    def test_a_tactic_with_no_emphasis_returns_the_same_catalogue(self) -> None:
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

    def test_emphasis_never_gives_a_role_an_attribute_it_ignores(self) -> None:
        # A centre-back has no stamina weight at all; a pressing tactic must not
        # invent one for him.
        self.assertNotIn("stamina", weights(MVP_CATALOGUE, "cd_defend"))
        derived = with_emphasis({"stamina": 2}).for_tactic(TACTIC)
        self.assertNotIn("stamina", weights(derived, "cd_defend"))

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

    def test_a_slot_block_overrides_the_tactic_block_for_that_slot_only(self) -> None:
        tactic = MVP_CATALOGUE.tactics[TACTIC]
        slots = list(tactic.slots)
        slots[6] = replace(slots[6], attribute_emphasis={"passing": 2})
        changed = replace(tactic, slots=tuple(slots), attribute_emphasis={"passing": 1})
        derived = replace(
            MVP_CATALOGUE, tactics={**MVP_CATALOGUE.tactics, TACTIC: changed}
        ).for_tactic(TACTIC)
        base = weights(MVP_CATALOGUE, "cm_defend")["passing"]
        role_key = slots[6].role_key
        self.assertEqual(
            {a.name: a.weight for a in derived.role_for_slot(slots[6], role_key).attributes}["passing"],
            base + 2,
        )
        # Every other slot keeps the tactic-wide +1.
        self.assertEqual(
            {a.name: a.weight for a in derived.role_for_slot(slots[7], "cm_support").attributes}["passing"],
            weights(MVP_CATALOGUE, "cm_support")["passing"] + 1,
        )


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
    """The committed seed stays inside the soft band it was measured at."""

    SEED_DELTA = 2
    MAX_ATTRIBUTES = 4

    def test_every_tactic_declares_an_emphasis(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertTrue(tactic.attribute_emphasis, tactic.key)

    def test_the_seed_stays_soft(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertLessEqual(
                len(tactic.attribute_emphasis), self.MAX_ATTRIBUTES, tactic.key
            )
            for attribute, delta in tactic.attribute_emphasis.items():
                self.assertLessEqual(
                    abs(delta), self.SEED_DELTA, f"{tactic.key}: {attribute} {delta:+d}"
                )

    def test_no_slot_level_emphasis_is_seeded(self) -> None:
        # Slot-level emphasis is reserved for deliberate hand tuning.
        for tactic in MVP_CATALOGUE.tactics.values():
            for slot in tactic.slots:
                self.assertEqual(slot.attribute_emphasis, {}, f"{tactic.key}/{slot.key}")

    def test_tactics_do_not_all_emphasise_the_same_attributes(self) -> None:
        # Emphasis exists to separate tactics; identical blocks everywhere would
        # be a weighting that says nothing.
        blocks = {
            frozenset(t.attribute_emphasis) for t in MVP_CATALOGUE.tactics.values()
        }
        self.assertGreaterEqual(len(blocks), len(MVP_CATALOGUE.tactics) // 3)


if __name__ == "__main__":
    unittest.main()

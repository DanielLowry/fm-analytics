"""Set-piece config validation, effective edits and unchanged scoring evidence."""

import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import asdict, replace
from enum import Enum
from pathlib import Path
from unittest.mock import patch

from fm_analytics.analytics import recommend_set_pieces
from fm_analytics.analytics import set_piece_routines
from fm_analytics.analytics.set_piece_config import DATA_DIR, load_set_piece_weights
from fm_analytics.analytics.set_pieces import SET_PIECE_TASKS, _build_taker_tasks
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility


CAPTURE = Path(__file__).parent / "fixtures/hungerford-vertical-442-2020-10-20.json"
BASELINE = Path(__file__).parent / "fixtures/set-piece-v11-config-migration.json"
RISKS = ("secure", "balanced", "aggressive")
VARIANTS = ("direct_free_kick", "direct_small_chance", "indirect_wide", "indirect_deep")


def known(value):
    return AttributeObservation(Visibility.KNOWN, value=value)


def fingerprint(value):
    # JSON loading makes weights floats; compare numeric meaning, including
    # every band/contribution, rather than integer-vs-float representation.
    def normalise(item):
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, bool):
            return item
        if isinstance(item, (int, float)):
            return float(item)
        if isinstance(item, dict):
            # The old free-kick roles carried unused placeholder attributes.
            # Actual delivery scores always use the task's dedicated/proxy
            # profile. Those scores/contributions and task definitions remain
            # fully covered; the role now also describes the real task profile.
            return {
                key: normalise(value) for key, value in item.items()
                if key != "attributes" or not item.get("taker_task_key")
            }
        if isinstance(item, (tuple, list)):
            return [normalise(value) for value in item]
        return item
    encoded = json.dumps(normalise(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def scenarios(squad):
    yield "captured", squad
    # These variations are synthetic test inputs, not additional game observations.
    yield "dedicated_and_feet", replace(squad, players=tuple(
        replace(player, preferred_foot=("Left", "Right", "Either")[index % 3], attributes={
            **player.attributes, "freeKickTaking": known(6 + index % 13),
            "penaltyTaking": known(7 + index % 12), "longThrows": known(5 + index % 14),
        }) for index, player in enumerate(squad.players)
    ))
    yield "mixed_evidence", replace(squad, players=tuple(
        replace(player, attributes={
            **player.attributes,
            "jumpingReach": AttributeObservation(Visibility.RANGE, minimum=5, maximum=13),
            "corners": AttributeObservation(Visibility.UNKNOWN) if index % 2 else player.attributes.get("corners", AttributeObservation(Visibility.UNKNOWN)),
            "freeKickTaking": AttributeObservation(Visibility.RANGE, minimum=8, maximum=14) if index % 2 else AttributeObservation(Visibility.UNKNOWN),
        }) for index, player in enumerate(squad.players)
    ))
    yield "unavailable", replace(squad, players=tuple(
        replace(player, injured=True) if player.name == "Ross Holden"
        else replace(player, suspended=True) if player.name == "Terrance Saydee"
        else player for player in squad.players
    ))


def definitions(module):
    return {
        "attacking_corners": {risk: [asdict(role) for role in module.attacking_roles("corner", risk)] for risk in RISKS},
        "defending_corners": [asdict(role) for role in module.defensive_roles("corner")],
        "attacking_free_kicks": {
            kind: {risk: [asdict(role) for role in module.attacking_roles(kind, risk)] for risk in RISKS}
            for kind in VARIANTS
        },
        "defending_free_kicks": {kind: [asdict(role) for role in module.defensive_roles(kind)] for kind in VARIANTS},
    }


class ConfigMigrationParityTests(unittest.TestCase):
    def test_all_roles_and_taker_rules_match_the_pre_migration_definitions(self):
        baseline = json.loads(BASELINE.read_text())
        self.assertEqual(fingerprint(definitions(set_piece_routines)), baseline["roles"])
        self.assertEqual(fingerprint([asdict(task) for task in SET_PIECE_TASKS]), baseline["tasks"])

    def test_every_routine_and_taker_score_matches_before_the_config_extraction(self):
        baseline = json.loads(BASELINE.read_text())["reports"]
        _, squad = load_fixture(CAPTURE)
        positions = json.loads(CAPTURE.read_text())["lineupPositions"]
        for scenario, players in scenarios(squad):
            for risk in RISKS:
                for delivery in ("inswinging", "outswinging"):
                    key = f"{scenario}/{risk}/{delivery}"
                    report = recommend_set_pieces(
                        players, selected_player_ids=tuple(positions), lineup_positions=positions,
                        attacking_risk=risk, delivery_style=delivery,
                    )
                    with self.subTest(scenario=scenario, risk=risk, delivery=delivery):
                        self.assertEqual(fingerprint(asdict(report)), baseline[key])


class SetPieceConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "weights"
        shutil.copytree(DATA_DIR, self.directory)

    def edit(self, filename, mutate):
        path = self.directory / filename
        document = json.loads(path.read_text())
        mutate(document)
        path.write_text(json.dumps(document))

    def test_shipped_config_exposes_all_families_and_variants(self):
        config = load_set_piece_weights(self.directory)
        self.assertEqual(config.version, "set-piece-v11")
        self.assertEqual(len(config.roles), 2)
        for family in ("attacking_free_kicks", "defending_free_kicks"):
            self.assertEqual(set(config.variants[family]), set(VARIANTS))
        self.assertEqual(set(config.tasks), {task.key for task in SET_PIECE_TASKS})

    def test_missing_role_is_rejected_with_its_file_and_job(self):
        self.edit("defending_corners.json", lambda d: d["roles"].pop("def_corner_zonal_centre"))
        with self.assertRaisesRegex(ValueError, "defending_corners.json.*def_corner_zonal_centre"):
            load_set_piece_weights(self.directory)

    def test_unknown_attribute_and_hidden_attributes_are_rejected(self):
        for attribute in ("jumpingRech", "currentAbility", "potentialAbility"):
            with self.subTest(attribute=attribute):
                self.edit("defending_corners.json", lambda d: d["profiles"].update({"zonal_defence": {attribute: 100}}))
                with self.assertRaisesRegex(ValueError, "unknown attributes"):
                    load_set_piece_weights(self.directory)

    def test_invalid_attribute_weights_are_rejected(self):
        for value in (-1, True, "20", None, float("nan"), float("inf"), 10 ** 400):
            with self.subTest(value=value):
                self.edit("defending_corners.json", lambda d: d["profiles"]["zonal_defence"].update(jumpingReach=value))
                with self.assertRaisesRegex(ValueError, "jumpingReach.*finite non-negative"):
                    load_set_piece_weights(self.directory)

    def test_empty_zero_and_overflowing_profiles_are_rejected(self):
        for value in ({}, {"heading": 0}, {"heading": 1e308, "jumpingReach": 1e308}):
            with self.subTest(profile=value):
                self.edit("defending_corners.json", lambda d: d["profiles"].update(zonal_defence=value))
                with self.assertRaisesRegex(ValueError, "weighted attribute|total attribute weight"):
                    load_set_piece_weights(self.directory)

    def test_invalid_responsibility_importance_is_rejected(self):
        for value in (0, -1, True, "1.6", None, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.edit("defending_corners.json", lambda d: d["roles"]["def_corner_zonal_centre"].update(importance=value))
                with self.assertRaisesRegex(ValueError, "importance.*finite positive"):
                    load_set_piece_weights(self.directory)

    def test_profile_references_must_exist(self):
        for value in ("misspelled_profile", None, []):
            with self.subTest(reference=value):
                self.edit("defending_corners.json", lambda d: d["roles"]["def_corner_zonal_centre"].update(profile=value))
                with self.assertRaisesRegex(ValueError, "unknown profile"):
                    load_set_piece_weights(self.directory)

    def test_no_unknown_keys_or_unused_profiles_are_silently_ignored(self):
        cases = (
            ("defending_corners.json", lambda d: d.update(unread_setting=1), "unexpected keys"),
            ("defending_corners.json", lambda d: d["roles"]["def_corner_zonal_centre"].update(importnace=1), "unexpected keys"),
            ("defending_corners.json", lambda d: d["profiles"].update(unused={"heading": 100}), "unused profiles"),
            ("attacking_corners.json", lambda d: d["tasks"]["corners"].update(unread=1), "unexpected keys"),
        )
        for filename, mutate, message in cases:
            with self.subTest(filename=filename, message=message):
                shutil.copytree(DATA_DIR, self.directory, dirs_exist_ok=True)
                self.edit(filename, mutate)
                with self.assertRaisesRegex(ValueError, message):
                    load_set_piece_weights(self.directory)

    def test_missing_and_unknown_free_kick_variants_are_rejected(self):
        for action in (lambda d: d["variants"].pop("indirect_deep"), lambda d: d["variants"].update(misspelling={})):
            shutil.copytree(DATA_DIR, self.directory, dirs_exist_ok=True)
            self.edit("attacking_free_kicks.json", action)
            with self.assertRaisesRegex(ValueError, "variants.*keys"):
                load_set_piece_weights(self.directory)

    def test_missing_taker_or_dedicated_profile_is_rejected(self):
        for action in (
            lambda d: d["tasks"].pop("direct_free_kicks"),
            lambda d: d["tasks"]["direct_free_kicks"].pop("dedicatedProfile"),
        ):
            shutil.copytree(DATA_DIR, self.directory, dirs_exist_ok=True)
            self.edit("attacking_free_kicks.json", action)
            with self.assertRaisesRegex(ValueError, "tasks.*missing keys"):
                load_set_piece_weights(self.directory)

    def test_missing_file_extra_file_and_malformed_json_fail_clearly(self):
        (self.directory / "penalties.json").unlink()
        with self.assertRaisesRegex(ValueError, "penalties.json"):
            load_set_piece_weights(self.directory)
        shutil.copytree(DATA_DIR, self.directory, dirs_exist_ok=True)
        (self.directory / "unused.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "unexpected files.*unused.json"):
            load_set_piece_weights(self.directory)
        (self.directory / "unused.json").unlink()
        (self.directory / "penalties.json").write_text("{")
        with self.assertRaisesRegex(ValueError, "penalties.json"):
            load_set_piece_weights(self.directory)

    def test_duplicate_json_keys_are_rejected(self):
        (self.directory / "model.json").write_text('{"version":"v1","version":"v2","deliveryFootBonus":4}')
        with self.assertRaisesRegex(ValueError, "model.json.*duplicate key 'version'"):
            load_set_piece_weights(self.directory)

    def test_nested_duplicate_attribute_keys_are_rejected(self):
        path = self.directory / "attacking_corners.json"
        path.write_text(path.read_text().replace('"corners": 60,', '"corners": 60, "corners": 20,', 1))
        with self.assertRaisesRegex(ValueError, "attacking_corners.json.*duplicate key 'corners'"):
            load_set_piece_weights(self.directory)

    def test_objects_and_profile_names_are_validated(self):
        cases = (
            (lambda d: d.update(profiles=[]), "profiles.*expected an object"),
            (lambda d: d.update(roles=[]), "roles.*expected an object"),
            (lambda d: d["roles"].update(def_corner_zonal_centre=[]), "def_corner_zonal_centre.*expected an object"),
            (lambda d: d["profiles"].update(zonal_defence=[]), "zonal_defence.*expected an object"),
            (lambda d: d["profiles"].update({" ": {"heading": 100}}), "profile names must not be empty"),
        )
        for mutate, message in cases:
            with self.subTest(message=message):
                shutil.copytree(DATA_DIR, self.directory, dirs_exist_ok=True)
                self.edit("defending_corners.json", mutate)
                with self.assertRaisesRegex(ValueError, message):
                    load_set_piece_weights(self.directory)

    def test_taker_jobs_must_reference_their_real_scoring_task(self):
        self.edit("attacking_corners.json", lambda d: d["roles"]["corner_taker"].update(profile="corner_taker"))
        with self.assertRaisesRegex(ValueError, "corner_taker.*unexpected keys.*profile"):
            load_set_piece_weights(self.directory)
        shutil.copytree(DATA_DIR, self.directory, dirs_exist_ok=True)
        self.edit("attacking_free_kicks.json", lambda d: d["variants"]["direct_free_kick"]["taker"].update(task="corners"))
        with self.assertRaisesRegex(ValueError, "direct_free_kick.taker.*task must be 'direct_free_kicks'"):
            load_set_piece_weights(self.directory)

    def test_dedicated_profiles_must_use_the_rating_they_claim(self):
        for family, profile, attribute in (
            ("attacking_free_kicks", "direct_free_kicks_dedicated", "freeKickTaking"),
            ("attacking_free_kicks", "indirect_free_kicks_dedicated", "freeKickTaking"),
            ("penalties", "penalties_dedicated", "penaltyTaking"),
        ):
            for bad in ({"technique": 100}, {attribute: 0, "technique": 100}):
                with self.subTest(profile=profile, bad=bad):
                    shutil.copytree(DATA_DIR, self.directory, dirs_exist_ok=True)
                    self.edit(family + ".json", lambda d: d["profiles"].update({profile: bad}))
                    with self.assertRaisesRegex(ValueError, "dedicatedProfile must weight " + attribute):
                        load_set_piece_weights(self.directory)

    def test_long_throws_cannot_be_inferred_from_unrelated_attributes(self):
        self.edit("long_throws.json", lambda d: d["profiles"].update(long_throws={"longThrows": 80, "strength": 20}))
        with self.assertRaisesRegex(ValueError, "long throws must use only the longThrows rating"):
            load_set_piece_weights(self.directory)

    def test_loaded_weights_cannot_be_mutated(self):
        config = load_set_piece_weights(self.directory)
        with self.assertRaises(TypeError):
            config.roles["defending_corners"]["def_corner_zonal_centre"] = None
        with self.assertRaises(TypeError):
            config.variants["attacking_free_kicks"]["indirect_wide"]["near"] = None
        with self.assertRaises(TypeError):
            config.tasks["corners"] = None

    def test_invalid_model_metadata_is_rejected(self):
        for value in ("", " ", None, 1):
            self.edit("model.json", lambda d: d.update(version=value))
            with self.assertRaisesRegex(ValueError, "version.*non-empty string"):
                load_set_piece_weights(self.directory)
        self.edit("model.json", lambda d: d.update(version="v1", deliveryFootBonus=-1))
        with self.assertRaisesRegex(ValueError, "deliveryFootBonus.*finite non-negative"):
            load_set_piece_weights(self.directory)

    def test_valid_attribute_ratios_need_not_total_one_hundred(self):
        self.edit("defending_corners.json", lambda d: d["profiles"].update(zonal_defence={"heading": 2, "jumpingReach": 1, "marking": 0}))
        config = load_set_piece_weights(self.directory)
        self.assertEqual(sum(a.weight for a in config.roles["defending_corners"]["def_corner_zonal_centre"].attributes), 3)

    def test_importance_edit_changes_real_team_assignment_only_in_its_family(self):
        _, squad = load_fixture(CAPTURE)
        original = recommend_set_pieces(squad)
        self.edit("defending_corners.json", lambda d: d["roles"]["def_corner_zonal_centre"].update(importance=0.1))
        config = load_set_piece_weights(self.directory)
        with patch.object(set_piece_routines, "SET_PIECE_WEIGHTS", config):
            revised = recommend_set_pieces(squad)
        before = {r.key: r for r in original.routines}
        for routine in revised.routines:
            if routine.key == "defending_corner":
                anchor = next(a for a in routine.assignments if a.role.key == "def_corner_zonal_centre")
                self.assertNotEqual(anchor.player.name, "Ejiro Okosieme")
                self.assertNotEqual(routine.score, before[routine.key].score)
            else:
                self.assertEqual(routine, before[routine.key])

    def test_one_free_kick_variant_can_change_without_affecting_other_variants(self):
        original = load_set_piece_weights(self.directory)
        self.edit("attacking_free_kicks.json", lambda d: d["variants"]["indirect_wide"]["near"].update(importance=2.5))
        revised = load_set_piece_weights(self.directory)
        for variant in VARIANTS:
            before, after = original.routine("attacking_free_kicks", variant), revised.routine("attacking_free_kicks", variant)
            self.assertEqual(before == after, variant != "indirect_wide")
        with patch.object(set_piece_routines, "SET_PIECE_WEIGHTS", revised):
            role = next(r for r in set_piece_routines.attacking_roles("indirect_wide", "balanced") if r.key == "indirect_wide_near")
        self.assertEqual(role.importance, 2.5)

    def test_corner_delivery_edit_controls_both_rankings_and_routine_taker_scores(self):
        _, squad = load_fixture(CAPTURE)
        self.edit("attacking_corners.json", lambda d: d["profiles"].update(corner_taker={"corners": 100}))
        config = load_set_piece_weights(self.directory)
        with patch.object(set_piece_routines, "SET_PIECE_WEIGHTS", config):
            report = recommend_set_pieces(squad, tasks=_build_taker_tasks(config))
        ranking = next(r for r in report.recommendations if r.task.key == "corners" and r.side == "left")
        self.assertEqual(ranking.suggested.player.name, "Ben Jefford")
        routine = next(r for r in report.routines if r.key == "attacking_corner_left")
        taker = next(a for a in routine.assignments if a.role.taker_task_key == "corners")
        self.assertEqual([a.name for a in taker.role.attributes], ["corners"])
        self.assertEqual([a.attribute for a in taker.score.contributions], ["corners"])
        self.assertAlmostEqual(taker.score.score.central, (taker.player.attributes["corners"].value - 1) * 100 / 19, places=5)

    def test_dedicated_taker_edit_does_not_change_the_missing_rating_proxy(self):
        _, squad = load_fixture(CAPTURE)
        player = squad.players[1]
        dedicated = replace(player, attributes={**player.attributes, "freeKickTaking": known(18)})
        original_task = next(t for t in SET_PIECE_TASKS if t.key == "direct_free_kicks")
        self.edit("attacking_free_kicks.json", lambda d: d["profiles"].update(direct_free_kicks_dedicated={"freeKickTaking": 100}))
        task = next(t for t in _build_taker_tasks(load_set_piece_weights(self.directory)) if t.key == "direct_free_kicks")
        self.assertEqual(task.evidence_mode(dedicated), "dedicated")
        self.assertAlmostEqual(task.score(dedicated).score.central, 17 * 100 / 19, places=5)
        self.assertNotEqual(task.score(dedicated).score, original_task.score(dedicated).score)
        self.assertEqual(task.evidence_mode(player), "proxy")
        self.assertEqual(task.score(player), original_task.score(player))

    def test_free_kick_routine_takers_share_the_real_dedicated_and_proxy_scores(self):
        _, squad = load_fixture(CAPTURE)
        self.edit("attacking_free_kicks.json", lambda d: d["profiles"].update(
            direct_free_kicks={"technique": 100},
            direct_free_kicks_dedicated={"freeKickTaking": 100},
            indirect_free_kicks={"crossing": 100},
            indirect_free_kicks_dedicated={"freeKickTaking": 100},
        ))
        config = load_set_piece_weights(self.directory)
        tasks = _build_taker_tasks(config)
        for evidence, players in scenarios(squad):
            if evidence not in {"captured", "dedicated_and_feet"}:
                continue
            with patch.object(set_piece_routines, "SET_PIECE_WEIGHTS", config):
                report = recommend_set_pieces(players, tasks=tasks)
            checked = 0
            for routine in report.routines:
                if not routine.key.startswith(tuple(f"attacking_{variant}_" for variant in VARIANTS)):
                    continue
                taker = next(a for a in routine.assignments if a.role.taker_task_key)
                task = next(t for t in tasks if t.key == taker.role.taker_task_key)
                with self.subTest(evidence=evidence, routine=routine.key):
                    self.assertEqual(taker.role.attributes, task.attributes)
                    self.assertEqual(taker.score, task.score(taker.player))
                    self.assertEqual(taker.evidence_mode, task.evidence_mode(taker.player))
                checked += 1
            self.assertEqual(checked, len(VARIANTS) * 2)


if __name__ == "__main__":
    unittest.main()

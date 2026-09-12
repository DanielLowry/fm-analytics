import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.domain.models import AttributeObservation, Visibility
from tools.fm20_visibility_capture import (
    EVENT_PREFIX,
    HIT_PREFIX,
    KNOWLEDGE_PREFIX,
    KNOWLEDGE_DECISION_PREFIX,
    IDENTITY_PREFIX,
    REPLAY_PREFIX,
    CaptureAccumulator,
    CaptureError,
    KnowledgeCacheEvent,
    KnowledgeDecisionEvent,
    ReplayEvent,
    VisibleCaptureEvent,
    build_gdb_environment,
    parse_diagnostic_hit,
    parse_event_line,
    parse_knowledge_event,
    parse_knowledge_decision,
    parse_identity_resolution,
    parse_replay_event,
    _verify_inferior_alive,
)


class VisibilityCaptureTests(unittest.TestCase):
    def test_parses_visible_range_event(self) -> None:
        event = parse_event_line(
            EVENT_PREFIX
            + json.dumps(
                {
                    "attribute_id": 0x27,
                    "lower": 5,
                    "player_id": 89065906,
                    "upper": 12,
                }
            )
        )

        self.assertEqual(
            event,
            VisibleCaptureEvent(
                player_id="89065906",
                attribute="acceleration",
                attribute_id="0x27",
                observation=AttributeObservation(
                    visibility=Visibility.RANGE,
                    minimum=5,
                    maximum=12,
                ),
            ),
        )

    def test_parses_unknown_from_visible_sentinels(self) -> None:
        event = parse_event_line(
            EVENT_PREFIX
            + json.dumps(
                {
                    "attribute_id": 0x28,
                    "lower": 0xFF,
                    "player_id": 89065906,
                    "upper": 0xFF,
                }
            )
        )

        self.assertEqual(event.observation.visibility, Visibility.UNKNOWN)

    def test_rejects_a_concealed_value_field(self) -> None:
        with self.assertRaisesRegex(CaptureError, "unexpected field contract"):
            parse_event_line(
                EVENT_PREFIX
                + json.dumps(
                    {
                        "attribute_id": 0x28,
                        "concealed": 17,
                        "lower": 0xFF,
                        "player_id": 89065906,
                        "upper": 0xFF,
                    }
                )
            )

    def test_ignores_non_event_gdb_output(self) -> None:
        self.assertIsNone(parse_event_line("[New LWP 123]"))

    def test_parses_diagnostic_hit_without_attribute_values(self) -> None:
        self.assertEqual(
            parse_diagnostic_hit(HIT_PREFIX + '{"attribute_id": 39}'),
            0x27,
        )

    def test_parses_manager_knowledge_cache_event(self) -> None:
        event = parse_knowledge_event(
            KNOWLEDGE_PREFIX
            + json.dumps(
                {
                    "context_address": 0x123400,
                    "context_owner_address": 0x456700,
                    "knowledge_level": 23,
                    "local_entry_count": 17,
                    "player_id": 89065906,
                    "player_row_id": 21533,
                    "record_address": 0x987600,
                }
            )
        )

        self.assertEqual(
            event,
            KnowledgeCacheEvent(
                context_address="0x123400",
                context_owner_address="0x456700",
                player_id="89065906",
                player_row_id="21533",
                record_address="0x987600",
                knowledge_level=23,
                local_entry_count=17,
            ),
        )

    def test_rejects_knowledge_without_a_record(self) -> None:
        with self.assertRaisesRegex(CaptureError, "missing knowledge record"):
            parse_knowledge_event(
                KNOWLEDGE_PREFIX
                + json.dumps(
                    {
                        "context_address": 1,
                        "context_owner_address": 2,
                        "knowledge_level": 23,
                        "local_entry_count": 0,
                        "player_id": 4,
                        "player_row_id": 3,
                        "record_address": 0,
                    }
                )
            )

    def test_parses_final_knowledge_decision(self) -> None:
        event = parse_knowledge_decision(
            KNOWLEDGE_DECISION_PREFIX
            + json.dumps(
                {
                    "attribute_id": 0x27,
                    "baseline_knowledge": 35,
                    "classification": "range",
                    "effective_knowledge": 60,
                    "exact_threshold": 80,
                    "explicit_knowledge": 60,
                    "merged_knowledge": 60,
                    "player_id": 89065906,
                    "range_threshold": 50,
                }
            )
        )

        self.assertEqual(
            event,
            KnowledgeDecisionEvent(
                player_id="89065906",
                attribute="acceleration",
                attribute_id="0x27",
                explicit_knowledge=60,
                baseline_knowledge=35,
                merged_knowledge=60,
                effective_knowledge=60,
                range_threshold=50,
                exact_threshold=80,
                classification="range",
            ),
        )

    def test_parses_matching_same_cell_replay(self) -> None:
        event = parse_replay_event(
            REPLAY_PREFIX
            + json.dumps(
                {
                    "attribute_id": 0x27,
                    "matched": True,
                    "player_id": 89065906,
                }
            )
        )

        self.assertEqual(
            event,
            ReplayEvent(
                player_id="89065906",
                attribute="acceleration",
                attribute_id="0x27",
                matched=True,
            ),
        )

    def test_rejects_a_replay_mismatch(self) -> None:
        accumulator = CaptureAccumulator()

        with self.assertRaisesRegex(CaptureError, "replay disagreed"):
            accumulator.add_replay(
                ReplayEvent("1", "acceleration", "0x27", matched=False)
            )

    def test_preserves_an_unmapped_knowledge_attribute_id(self) -> None:
        event = parse_knowledge_decision(
            KNOWLEDGE_DECISION_PREFIX
            + json.dumps(
                {
                    "attribute_id": 0x7F,
                    "baseline_knowledge": 35,
                    "classification": "range",
                    "effective_knowledge": 60,
                    "exact_threshold": 80,
                    "explicit_knowledge": 60,
                    "merged_knowledge": 60,
                    "player_id": 89065906,
                    "range_threshold": 50,
                }
            )
        )

        self.assertIsNone(event.attribute)
        self.assertEqual(event.attribute_id, "0x7f")

    def test_rejects_an_incorrect_knowledge_merge(self) -> None:
        with self.assertRaisesRegex(CaptureError, "merge rule"):
            parse_knowledge_decision(
                KNOWLEDGE_DECISION_PREFIX
                + json.dumps(
                    {
                        "attribute_id": 0x27,
                        "baseline_knowledge": 35,
                        "classification": "range",
                        "effective_knowledge": 60,
                        "exact_threshold": 80,
                        "explicit_knowledge": 60,
                        "merged_knowledge": 40,
                        "player_id": 89065906,
                        "range_threshold": 50,
                    }
                )
            )

    def test_deduplicates_identical_events(self) -> None:
        event = VisibleCaptureEvent(
            player_id="1",
            attribute="acceleration",
            attribute_id="0x27",
            observation=AttributeObservation(Visibility.KNOWN, value=12),
        )
        accumulator = CaptureAccumulator()

        accumulator.add(event)
        accumulator.add(event)
        accumulator.record_hook_hit(0x27)
        accumulator.add_knowledge_event(
            KnowledgeCacheEvent("0x1", "0x2", "1", "2", "0x3", 20, 1)
        )

        self.assertEqual(accumulator.raw_event_count, 2)
        self.assertEqual(accumulator.hook_hit_count, 1)
        self.assertEqual(accumulator.diagnostic_attribute_ids, {0x27})
        self.assertEqual(len(accumulator.knowledge_events), 1)
        self.assertEqual(accumulator.observations, (event,))

    def test_validates_matching_visible_and_knowledge_classifications(self) -> None:
        accumulator = CaptureAccumulator()
        accumulator.add(
            VisibleCaptureEvent(
                player_id="1",
                attribute="acceleration",
                attribute_id="0x27",
                observation=AttributeObservation(
                    Visibility.RANGE,
                    minimum=5,
                    maximum=12,
                ),
            )
        )
        accumulator.add_knowledge_decision(
            KnowledgeDecisionEvent(
                player_id="1",
                attribute="acceleration",
                attribute_id="0x27",
                explicit_knowledge=0,
                baseline_knowledge=12,
                merged_knowledge=12,
                effective_knowledge=12,
                range_threshold=5,
                exact_threshold=43,
                classification="range",
            )
        )

        accumulator.validate_knowledge_alignment()

    def test_rejects_missing_or_disagreeing_knowledge_classifications(self) -> None:
        accumulator = CaptureAccumulator()
        accumulator.add(
            VisibleCaptureEvent(
                player_id="1",
                attribute="acceleration",
                attribute_id="0x27",
                observation=AttributeObservation(Visibility.UNKNOWN),
            )
        )
        with self.assertRaisesRegex(CaptureError, "no matching"):
            accumulator.validate_knowledge_alignment()

        accumulator.add_knowledge_decision(
            KnowledgeDecisionEvent(
                player_id="1",
                attribute="acceleration",
                attribute_id="0x27",
                explicit_knowledge=0,
                baseline_knowledge=12,
                merged_knowledge=12,
                effective_knowledge=12,
                range_threshold=5,
                exact_threshold=43,
                classification="range",
            )
        )
        with self.assertRaisesRegex(CaptureError, "disagrees"):
            accumulator.validate_knowledge_alignment()

    def test_parses_interface_identity_resolution_without_an_address(self) -> None:
        self.assertEqual(
            parse_identity_resolution(
                IDENTITY_PREFIX
                + json.dumps({"offset": -0x1C8, "status": "interface-person"})
            ),
            "interface-person@-0x1c8",
        )

    def test_rejects_interface_identity_without_an_adjustment(self) -> None:
        with self.assertRaisesRegex(CaptureError, "requires a bounded adjustment"):
            parse_identity_resolution(
                IDENTITY_PREFIX
                + json.dumps({"offset": None, "status": "interface-person"})
            )

    def test_rejects_conflicting_events_in_one_capture(self) -> None:
        accumulator = CaptureAccumulator()
        accumulator.add(
            VisibleCaptureEvent(
                "1",
                "acceleration",
                "0x27",
                AttributeObservation(Visibility.KNOWN, value=12),
            )
        )

        with self.assertRaisesRegex(CaptureError, "conflicting"):
            accumulator.add(
                VisibleCaptureEvent(
                    "1",
                    "acceleration",
                    "0x27",
                    AttributeObservation(Visibility.KNOWN, value=13),
                )
            )

    def test_builds_narrow_gdb_environment(self) -> None:
        environment = build_gdb_environment(
            {"EXISTING": "yes"},
            0x140000000,
            ("acceleration", "agility"),
            (89065906,),
            diagnostic_hits=True,
            trace_knowledge_cache=True,
            trace_knowledge_decision=True,
            replay_same_cell=True,
        )

        self.assertEqual(environment["EXISTING"], "yes")
        self.assertEqual(environment["FMVIS_BREAKPOINT"], "0x141d97a3e")
        self.assertEqual(environment["FMVIS_MODULE_BASE"], "0x140000000")
        self.assertEqual(environment["FMVIS_ATTRIBUTE_IDS"], "0x27,0x28")
        self.assertEqual(environment["FMVIS_PLAYER_IDS"], "89065906")
        self.assertEqual(environment["FMVIS_DIAGNOSTIC_HITS"], "1")
        self.assertEqual(environment["FMVIS_TRACE_KNOWLEDGE_CACHE"], "1")
        self.assertEqual(
            environment["FMVIS_KNOWLEDGE_BREAKPOINT"],
            "0x1415a51c3",
        )
        self.assertEqual(environment["FMVIS_TRACE_KNOWLEDGE_DECISION"], "1")
        self.assertEqual(
            environment["FMVIS_KNOWLEDGE_CONTEXT_ENTRY_BREAKPOINT"],
            "0x1415a4dc0",
        )
        self.assertEqual(
            environment["FMVIS_KNOWLEDGE_DECISION_ENTRY_BREAKPOINT"],
            "0x1415a51b5",
        )
        self.assertEqual(
            environment["FMVIS_KNOWLEDGE_DECISION_MERGE_BREAKPOINT"],
            "0x1415a51dc",
        )
        self.assertEqual(
            environment["FMVIS_KNOWLEDGE_DECISION_RESULT_BREAKPOINT"],
            "0x1415a52b5",
        )
        self.assertEqual(
            environment["FMVIS_VISIBLE_RESULT_BUILDER_BREAKPOINT"],
            "0x1415a4a90",
        )
        self.assertEqual(environment["FMVIS_REPLAY_SAME_CELL"], "1")

    def test_post_detach_liveness_check_rejects_a_missing_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(CaptureError, "exited during"):
                _verify_inferior_alive(123, Path(temporary_directory))

    def test_post_detach_liveness_check_accepts_a_present_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            process_dir = Path(temporary_directory) / "123"
            process_dir.mkdir()

            _verify_inferior_alive(123, Path(temporary_directory))


if __name__ == "__main__":
    unittest.main()

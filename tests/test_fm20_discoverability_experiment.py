import struct
from types import SimpleNamespace

from tools.fm20_discoverability_experiment import (
    build_capture_report,
    build_study_report,
    compare_candidate_reports,
    parse_done_line,
    resolve_source_vector_ids,
)
from tools.fm20_linux_probe import ProbeError


def _probe(*, date: str = "2020-01-01", manager_id: str = "42"):
    return SimpleNamespace(
        pid=1234,
        game_date=date,
        human_managers=(SimpleNamespace(id=manager_id, active=True),),
        expected_product_version="20.4.4-1442341",
        profile="FM20 20.4.4 Steam/Windows executable",
    )


def _capture(state: str, pairs: list[tuple[int, int | None]], count: int):
    return build_capture_report(
        state=state,
        kind="candidates",
        ui_count=count,
        trace={
            "_candidate_pointer_ids": pairs,
            "_candidate_identity_offsets": [456, 672],
        },
        before=_probe(),
        after=_probe(),
    )


def test_done_line_requires_explicit_count():
    assert parse_done_line("done 4320\n") == 4320
    assert parse_done_line("DONE 0") == 0
    assert parse_done_line("done") is None
    assert parse_done_line("4320") is None
    assert parse_done_line("done -1") is None


def test_candidate_capture_checks_complete_unique_ids_and_ui_count():
    report = _capture("no-package", [(100, 10), (200, 20)], 2)
    assert report["passed"] is True
    assert report["playerIds"] == [10, 20]
    assert report["candidatePointerCount"] == 2
    assert report["checks"]["allIdentitiesResolved"] is True
    assert report["checks"]["matchesUiCount"] is True


def test_candidate_capture_fails_closed_on_missing_or_duplicate_ids():
    missing = _capture("no-package", [(100, 10), (200, None)], 2)
    duplicate = _capture("no-package", [(100, 10), (200, 10)], 2)
    assert missing["passed"] is False
    assert missing["checks"]["allIdentitiesResolved"] is False
    assert duplicate["passed"] is False
    assert duplicate["checks"]["uniquePlayerIds"] is False


def test_source_capture_records_vector_without_assuming_it_matches_ui_count():
    report = build_capture_report(
        state="senior-vanarama",
        kind="source",
        ui_count=4933,
        trace={"_search_source_events": [{"vector_count": 162072}]},
        before=_probe(),
        after=_probe(),
    )
    assert report["passed"] is True
    assert report["sourceVectorCounts"] == [162072]


def test_comparison_reports_exact_subset_and_delta():
    base = _capture("no-package", [(100, 10), (200, 20)], 2)
    expanded = _capture("senior-vanarama", [(100, 10), (200, 20), (300, 30)], 3)
    report = compare_candidate_reports(base, expanded)
    assert report["passed"] is True
    assert report["sharedCount"] == 2
    assert report["addedPlayerIds"] == [30]
    assert report["removedPlayerIds"] == []


def test_comparison_fails_when_base_member_disappears():
    base = _capture("no-package", [(100, 10), (200, 20)], 2)
    expanded = _capture("senior-vanarama", [(100, 10), (300, 30)], 2)
    report = compare_candidate_reports(base, expanded)
    assert report["passed"] is False
    assert report["removedPlayerIds"] == [20]
    assert report["checks"]["baseIsSubset"] is False


def test_source_vector_resolves_normal_and_dual_role_players():
    module_base = 0x10000000
    memory = {
        (0x1000 + 0xD0, 16): struct.pack("<QQ", 0x2000, 0x2010),
        (0x2000, 16): struct.pack("<QQ", 0x3000, 0x3010),
        (0x3000, 8): struct.pack("<Q", 0x4000),
        (0x3010, 8): struct.pack("<Q", 0x4010),
        (0x4000, 16): struct.pack("<Qii", module_base + 0x6D92778, 1, 42),
        (0x4010, 16): struct.pack("<Qii", module_base + 0x6DA94A0, 2, 17),
    }
    events = [{"source_pointer": 0x1000, "vector_begin": 0x2000,
               "vector_end": 0x2010, "vector_count": 2}]
    ids = resolve_source_vector_ids(lambda address, size: memory[(address, size)],
                                    module_base, events)
    assert ids == [17, 42]


def test_source_vector_refuses_changed_or_unobserved_snapshot():
    try:
        resolve_source_vector_ids(lambda address, size: b"", 0x10000000, [])
    except ProbeError:
        pass
    else:
        assert False, "unobserved source must fail"
    events = [{"source_pointer": 0x1000, "vector_begin": 0x2000,
               "vector_end": 0x2008, "vector_count": 1}]
    try:
        resolve_source_vector_ids(lambda address, size: struct.pack("<QQ", 0x3000, 0x3008),
                                  0x10000000, events)
    except ProbeError as exc:
        assert "moved" in str(exc)
    else:
        assert False, "moved source must fail"


def test_study_compares_candidate_and_source_deltas():
    base_candidate = _capture("no-package", [(100, 10), (200, 20)], 2)
    expanded_candidate = _capture("senior-vanarama", [(100, 10), (200, 20),
                                                         (300, 30)], 3)
    base = {"stateLabel": "no-package", "candidateCapture": base_candidate,
            "sourcePlayerIds": [10, 20, 99], "sourceOnlyPlayerIds": [99],
            "gameDate": "2020-01-01", "activeManagerId": "42",
            "productVersion": "20.4.4-1442341", "passed": True}
    expanded = {"stateLabel": "senior-vanarama", "candidateCapture": expanded_candidate,
                "sourcePlayerIds": [10, 20, 30, 99], "sourceOnlyPlayerIds": [99],
                "gameDate": "2020-01-01", "activeManagerId": "42",
                "productVersion": "20.4.4-1442341", "passed": True}
    report = build_study_report(base, expanded)
    assert report["passed"] is True
    assert report["candidateComparison"]["addedPlayerIds"] == [30]
    assert report["sourceComparison"]["addedPlayerIds"] == [30]
    assert report["sourceComparison"]["sourceOnlyBasePlayerIds"] == [99]


def _three_player_source(third_type_rva, third_row, third_id):
    module_base = 0x10000000
    memory = {
        (0x1000 + 0xD0, 16): struct.pack("<QQ", 0x2000, 0x2018),
        (0x2000, 24): struct.pack("<QQQ", 0x3000, 0x3010, 0x3020),
        (0x3000, 8): struct.pack("<Q", 0x4000),
        (0x3010, 8): struct.pack("<Q", 0x4010),
        (0x3020, 8): struct.pack("<Q", 0x4020),
        (0x4000, 16): struct.pack("<Qii", module_base + 0x6D92778, 1, 42),
        (0x4010, 16): struct.pack("<Qii", module_base + 0x6D92778, 2, 17),
        (0x4020, 16): struct.pack("<Qii", module_base + third_type_rva, third_row, third_id),
    }
    events = [{"source_pointer": 0x1000, "vector_begin": 0x2000,
               "vector_end": 0x2018, "vector_count": 3}]
    return lambda address, size: memory[(address, size)], module_base, events


def test_a_real_player_with_no_id_is_skipped_not_fatal():
    # Seen live: Bradley Bubb, a genuine player record FM had given ID -1,
    # aborted every scouting refresh while he was in the search.
    read, module_base, events = _three_player_source(0x6D92778, 31403, -1)
    assert resolve_source_vector_ids(read, module_base, events) == [17, 42]


def test_a_record_that_is_not_a_player_still_fails():
    read, module_base, events = _three_player_source(0x1234, 31403, -1)
    try:
        resolve_source_vector_ids(read, module_base, events)
    except ProbeError as exc:
        assert "unresolved player" in str(exc)
    else:
        assert False, "a non-player record must still be refused"

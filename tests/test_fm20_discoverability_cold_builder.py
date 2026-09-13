import struct

from tools.fm20_discoverability_cold_builder import derive_builder_arguments
from tools.fm20_linux_probe import ProbeError


def _fixture():
    source = 0x1000
    filter_context = 0x2000
    call_context = 0x3030
    scope = 0x4000
    memory = {
        (source + 0x24, 1): b"\x01",
        (source, 8): struct.pack("<Q", filter_context),
        (call_context - 0x28, 8): struct.pack("<Q", filter_context),
        (call_context - 0x20, 8): struct.pack("<Q", scope),
    }
    event = {"source_pointer": source, "filter_pointer": filter_context,
             "context_pointer": call_context}
    return memory, event, scope


def test_builder_arguments_resolve_from_stable_saved_trace():
    memory, event, scope = _fixture()
    assert derive_builder_arguments(lambda address, size: memory[(address, size)],
                                    [event, event]) == (0x1000, 0x2000, scope)


def test_builder_arguments_reject_stale_context():
    memory, event, _ = _fixture()
    memory[(0x1000, 8)] = struct.pack("<Q", 0x9999)
    try:
        derive_builder_arguments(lambda address, size: memory[(address, size)], [event])
    except ProbeError as exc:
        assert "no longer matches" in str(exc)
    else:
        assert False, "stale source context must fail"


def test_builder_arguments_reject_ambiguous_capture():
    memory, event, _ = _fixture()
    other = {**event, "context_pointer": 0x5030}
    try:
        derive_builder_arguments(lambda address, size: memory[(address, size)],
                                 [event, other])
    except ProbeError as exc:
        assert "changed" in str(exc)
    else:
        assert False, "ambiguous search context must fail"

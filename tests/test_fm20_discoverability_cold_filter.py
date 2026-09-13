import struct

from tools.fm20_discoverability_cold_filter import (
    FILTER_EVALUATOR_RVA,
    FILTER_VTABLE_RVA,
    RULE_EVALUATOR_RVA,
    RULE_VTABLE_RVA,
    resolve_full_filter,
    resolve_native_rule,
)
from tools.fm20_linux_probe import ProbeError


def _fixture():
    base = 0x100000000
    source, filter_object, rule_vector, begin, rule = (
        0x1000, 0x2000, 0x3000, 0x4000, 0x5000
    )
    memory = {
        (source + 0x78, 8): struct.pack("<Q", filter_object),
        (filter_object, 8): struct.pack("<Q", base + FILTER_VTABLE_RVA),
        (filter_object + 0x30, 8): struct.pack("<Q", rule_vector),
        (rule_vector, 16): struct.pack("<QQ", begin, begin + 8),
        (begin, 8): struct.pack("<Q", rule),
        (rule, 8): struct.pack("<Q", base + RULE_VTABLE_RVA),
        (base + RULE_VTABLE_RVA + 0x88, 8): struct.pack(
            "<Q", base + RULE_EVALUATOR_RVA
        ),
        (base + FILTER_VTABLE_RVA + 0x48, 8): struct.pack(
            "<Q", base + FILTER_EVALUATOR_RVA
        ),
        (rule + 0x10, 1): b"\x00",
    }
    return base, source, memory


def test_pinned_native_rule_and_full_filter_resolve():
    base, source, memory = _fixture()
    reader = lambda address, size: memory[(address, size)]
    assert resolve_native_rule(reader, base, source) == 0x5000
    assert resolve_full_filter(reader, base, source) == 0x2000


def test_native_rule_rejects_non_default_mode():
    base, source, memory = _fixture()
    memory[(0x5000 + 0x10, 1)] = b"\x01"
    try:
        resolve_native_rule(lambda address, size: memory[(address, size)], base, source)
    except ProbeError as exc:
        assert "default mode" in str(exc)
    else:
        assert False, "changed native filter mode must fail"

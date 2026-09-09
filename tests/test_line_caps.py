"""Enforce a hard line cap and healthy source-file size distribution.

Prefer splitting a genuinely oversized module along cohesive responsibilities.
Do not condense code, trim useful comments, or create tiny artificial modules
merely to satisfy these tests.

Hard cap: 1000 lines per source file.
Median:   under 250 lines.
P75:      under 400 lines.
P90:      under 550 lines.
P95:      under 750 lines.
P99:      under 900 lines.
"""

from __future__ import annotations

import unittest
from pathlib import Path


HARD_CAP = 1000
MEDIAN_TARGET = 250
P75_TARGET = 400
P90_TARGET = 550
P95_TARGET = 750
P99_TARGET = 900

SKIP_DIRS = {
    ".agents",
    ".codex",
    ".git",
    ".venv",
    "__pycache__",
    "bin",
    "build",
    "dist",
    "migrations",
    "obj",
}
SKIP_PREFIXES = (".", "_")
SOURCE_EXTENSIONS = {".cs", ".css", ".html", ".js", ".py", ".ts", ".tsx"}
HARD_OVERRIDES: dict[str, int] = {}
ROOT = Path(__file__).resolve().parent.parent


def _iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if any(part.startswith(SKIP_PREFIXES) for part in relative.parts):
            continue
        if path.suffix not in SOURCE_EXTENSIONS:
            continue
        files.append(path)
    return sorted(files)


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as source_file:
        return sum(1 for _ in source_file)


def _percentile(sorted_counts: list[int], percentile: int) -> int:
    """Return a percentile using the nearest-rank method."""
    if not sorted_counts:
        return 0
    rank = max(1, (percentile * len(sorted_counts) + 99) // 100)
    return sorted_counts[rank - 1]


class LineCapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.files = _iter_source_files(ROOT)
        cls.counts = sorted(_line_count(path) for path in cls.files)
        if not cls.counts:
            raise AssertionError("line-cap test did not discover any source files")

    def test_hard_cap(self) -> None:
        """No individual source file should exceed 1,000 lines."""
        violations: list[str] = []
        for path in self.files:
            relative = path.relative_to(ROOT)
            limit = HARD_OVERRIDES.get(str(relative), HARD_CAP)
            count = _line_count(path)
            if count > limit:
                violations.append(f"{relative}: {count} lines (cap: {limit})")
        self.assertFalse(
            violations,
            "Oversized source files should be split into cohesive modules:\n"
            + "\n".join(violations),
        )

    def test_median_cap(self) -> None:
        median = self.counts[len(self.counts) // 2]
        self.assertLess(
            median,
            MEDIAN_TARGET,
            f"Median across {len(self.counts)} files is {median}; "
            f"target is < {MEDIAN_TARGET}",
        )

    def _assert_percentile(self, percentile: int, target: int) -> None:
        actual = _percentile(self.counts, percentile)
        self.assertLess(
            actual,
            target,
            f"P{percentile} across {len(self.counts)} files is {actual}; "
            f"target is < {target}",
        )

    def test_p75_cap(self) -> None:
        self._assert_percentile(75, P75_TARGET)

    def test_p90_cap(self) -> None:
        self._assert_percentile(90, P90_TARGET)

    def test_p95_cap(self) -> None:
        self._assert_percentile(95, P95_TARGET)

    def test_p99_cap(self) -> None:
        self._assert_percentile(99, P99_TARGET)


if __name__ == "__main__":
    unittest.main()


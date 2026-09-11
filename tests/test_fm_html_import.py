import unittest

from fm_analytics.domain import Visibility
from fm_analytics.imports import (
    merge_fm_html_exports,
    parse_attribute_cell,
    parse_fm_html_export,
    verify_export_completeness,
)


HTML = """
<!doctype html>
<html><body>
  <table><tr><th>Summary</th></tr><tr><td>Not the player table</td></tr></table>
  <table>
    <tr>
      <th>UID</th><th>Name</th><th>Position</th>
      <th>Pas</th><th>Vis</th><th>Wor</th>
    </tr>
    <tr>
      <td>101</td><td>Alex Exact</td><td>M/AM (LC)</td>
      <td>15</td><td>14</td><td> - </td>
    </tr>
    <tr>
      <td>r-202</td><td>Jamie Range</td><td>D (RC), DM</td>
      <td>10 - 14</td><td>?</td><td>12–16</td>
    </tr>
  </table>
</body></html>
"""


class FmHtmlImportTests(unittest.TestCase):
    def test_parses_manager_visible_exact_range_and_unknown_cells(self) -> None:
        export = parse_fm_html_export(HTML)

        self.assertEqual(export.source, "fm20-ui-html")
        self.assertEqual(len(export.players), 2)
        exact, ranged = export.players
        self.assertEqual(exact.positions, ("ML", "MC", "AML", "AMC"))
        self.assertEqual(exact.attributes["passing"].value, 15)
        self.assertEqual(exact.attributes["workRate"].visibility, Visibility.UNKNOWN)
        self.assertEqual(ranged.positions, ("DR", "DC", "DM"))
        self.assertEqual(
            ranged.attributes["passing"].to_dict(),
            {"visibility": "range", "minimum": 10, "maximum": 14},
        )
        self.assertEqual(
            ranged.attributes["workRate"].to_dict(),
            {"visibility": "range", "minimum": 12, "maximum": 16},
        )

    def test_attribute_parser_rejects_non_visible_or_invalid_values(self) -> None:
        for value in ("0", "21", "very good", "10-21"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_attribute_cell(value)

    def test_rejects_export_without_stable_identity(self) -> None:
        html = "<table><tr><th>Name</th><th>Position</th><th>Pas</th></tr>" \
            "<tr><td>A</td><td>MC</td><td>10</td></tr></table>"

        with self.assertRaisesRegex(ValueError, "UID"):
            parse_fm_html_export(html)

    def test_rejects_duplicate_player_ids(self) -> None:
        html = HTML.replace("r-202", "101")

        with self.assertRaisesRegex(ValueError, "duplicate UID"):
            parse_fm_html_export(html)

    def test_rejects_malformed_row_instead_of_silently_dropping_player(self) -> None:
        html = HTML.replace("<td>12–16</td>", "")

        with self.assertRaisesRegex(ValueError, "row 3 has 5 cells"):
            parse_fm_html_export(html)

    def test_requires_at_least_one_recognized_attribute(self) -> None:
        html = "<table><tr><th>UID</th><th>Name</th><th>Position</th></tr>" \
            "<tr><td>1</td><td>A</td><td>GK</td></tr></table>"

        with self.assertRaisesRegex(ValueError, "no recognized attribute"):
            parse_fm_html_export(html)

    def test_merges_pages_and_deduplicates_identical_overlap(self) -> None:
        first = parse_fm_html_export(HTML)
        second = parse_fm_html_export(
            HTML.replace("<td>101</td>", "<td>303</td>")
            .replace("<td>r-202</td>", "<td>101</td>")
            .replace("<td>Jamie Range</td>", "<td>Alex Exact</td>")
            .replace("<td>D (RC), DM</td>", "<td>M/AM (LC)</td>")
            .replace(
                "<td>10 - 14</td><td>?</td><td>12–16</td>",
                "<td>15</td><td>14</td><td> - </td>",
            )
        )

        combined = merge_fm_html_exports((first, second))

        self.assertEqual(
            [player.id for player in combined.players],
            ["101", "r-202", "303"],
        )

    def test_merge_rejects_conflicting_duplicate_identity(self) -> None:
        first = parse_fm_html_export(HTML)
        changed = parse_fm_html_export(HTML.replace("Alex Exact", "Different Name"))

        with self.assertRaisesRegex(ValueError, "conflicting rows"):
            merge_fm_html_exports((first, changed))

    def test_completeness_uses_unique_merged_player_count(self) -> None:
        export = parse_fm_html_export(HTML)

        result = verify_export_completeness(export, expected_players=2)

        self.assertTrue(result.is_complete)
        self.assertEqual(result.imported_players, 2)

    def test_completeness_rejects_missing_or_extra_players(self) -> None:
        export = parse_fm_html_export(HTML)

        with self.assertRaisesRegex(
            ValueError,
            "imported 2 unique players but FM shows 3",
        ):
            verify_export_completeness(export, expected_players=3)

    def test_completeness_rejects_invalid_expected_count(self) -> None:
        export = parse_fm_html_export(HTML)

        with self.assertRaisesRegex(ValueError, "at least 1"):
            verify_export_completeness(export, expected_players=0)


if __name__ == "__main__":
    unittest.main()

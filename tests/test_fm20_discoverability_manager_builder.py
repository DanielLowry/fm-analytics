import argparse
import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.fm20_discoverability_manager_builder import _guided_ab, resolve_manager_source
from tools.fm20_linux_probe import FM20_4_4_STEAM, ProbeError


class ManagerSourceTests(unittest.TestCase):
    def _memory(self):
        module = 0x140000000
        person = 0x5000
        manager = person - 0x480
        team = 0x6000
        array = 0x7000
        source = 0x8000
        memory = {
            (person, 8): struct.pack("<Q", module + FM20_4_4_STEAM.human_manager_type_offset),
            (manager, 8): struct.pack("<Q", module + 0x6D80CA0),
            (team, 8): struct.pack("<Q", module + 0x6D8DBC0),
            (team + 0x80, 8): struct.pack("<Q", manager),
            (manager + 0x190, 24): struct.pack("<QQQ", array, array + 8, array + 16),
            (array, 8): struct.pack("<Q", source),
            (source + 0x24, 1): b"\x01",
            (source, 8): struct.pack("<Q", manager),
        }
        return module, person, team, source, memory

    def test_resolves_player_source_from_manager_without_saved_pointer(self):
        module, person, team, source, memory = self._memory()
        self.assertEqual(
            resolve_manager_source(lambda address, size: memory[(address, size)],
                                   module, person, team),
            (source, person - 0x480, team),
        )

    def test_rejects_team_from_another_manager(self):
        module, person, team, _, memory = self._memory()
        memory[(team + 0x80, 8)] = struct.pack("<Q", 0x9999)
        with self.assertRaisesRegex(ProbeError, "point back"):
            resolve_manager_source(lambda address, size: memory[(address, size)],
                                   module, person, team)

    def test_guided_ab_runs_all_native_phases_before_ui_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory) / "previous.json"
            previous.write_text(json.dumps({"pid": 10}), encoding="utf-8")
            args = argparse.Namespace(previous_report=previous)
            manager = SimpleNamespace(active=True, id="42")
            state = SimpleNamespace(game_date="2019-06-24", human_managers=[manager])
            phase = {"beforeCount": 4953, "afterCount": 4953,
                     "afterMatchesOracle": True, "passed": True}
            with (patch("tools.fm20_discoverability_manager_builder.sys.stdin",
                        SimpleNamespace(isatty=lambda: True)),
                  patch("tools.fm20_discoverability_manager_builder._prompt"),
                  patch("tools.fm20_discoverability_manager_builder._live_context",
                        return_value=(state, (1, 2, 3), [1])),
                  patch("tools.fm20_discoverability_manager_builder.run_phase",
                        return_value=phase) as run_phase,
                  patch("builtins.input", return_value="4933")):
                report = _guided_ab(args, 11, {"senior-vanarama": [1],
                                               "no-package": [1]})
        self.assertTrue(report["passed"])
        self.assertEqual(report["initialSource"]["available"], True)
        self.assertEqual(run_phase.call_count, 3)
        self.assertEqual([item[0][1] for item in run_phase.call_args_list],
                         ["senior-vanarama", "no-package", "senior-vanarama"])


if __name__ == "__main__":
    unittest.main()

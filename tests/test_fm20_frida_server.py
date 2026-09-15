import tempfile
import unittest
from pathlib import Path

from tools.fm20_frida_server import (
    FridaServerError,
    proton_configuration,
    verify_server_binary,
)


class FridaServerTests(unittest.TestCase):
    def test_verifies_pinned_server_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.exe"
            path.write_bytes(b"wrong")
            with self.assertRaisesRegex(FridaServerError, "checksum"):
                verify_server_binary(path)

    def test_resolves_proton_from_steam_compat_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            steamapps = root / "client" / "steamapps"
            executable = steamapps / "common" / "Game" / "fm.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            proton_root = root / "client" / "steamapps" / "common" / "Proton Test"
            (proton_root / "files" / "share" / "default_pfx").mkdir(parents=True)
            (proton_root / "proton").touch()
            config = steamapps / "compatdata" / "1100600" / "config_info"
            config.parent.mkdir(parents=True)
            config.write_text(
                f"1.0\n{proton_root}/files/share/default_pfx/\n",
                encoding="utf-8",
            )

            proton, client, compat_data = proton_configuration(executable)

            self.assertEqual(proton, proton_root / "proton")
            self.assertEqual(client, root / "client")
            self.assertEqual(compat_data, steamapps / "compatdata" / "1100600")


if __name__ == "__main__":
    unittest.main()

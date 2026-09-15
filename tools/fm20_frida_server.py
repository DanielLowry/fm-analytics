"""Lifecycle manager for a Windows Frida server inside FM's Proton prefix."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "1100600"
SERVER_VERSION = "17.18.0"
SERVER_NAME = f"frida-server-{SERVER_VERSION}-windows-x86_64.exe"
SERVER_PATH = ROOT / "data" / "research" / "runtime" / SERVER_NAME
SERVER_SHA256 = "cce59bc04bba442ba02d493324e64f599a3b70faeb727cc9feef11e6bfdb88d6"
DEFAULT_ADDRESS = "127.0.0.1:27044"


class FridaServerError(RuntimeError):
    """The isolated Windows-side Frida server could not be managed safely."""


def verify_server_binary(path: Path = SERVER_PATH) -> Path:
    if not path.is_file():
        raise FridaServerError(
            f"verified Windows Frida server is missing: {path}; run the research setup first"
        )
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != SERVER_SHA256:
        raise FridaServerError("Windows Frida server checksum does not match the pinned release")
    return path


def proton_configuration(executable: Path) -> tuple[Path, Path, Path]:
    steamapps = next((parent for parent in executable.parents if parent.name == "steamapps"), None)
    if steamapps is None:
        raise FridaServerError("FM executable is not inside a Steam library")
    compat_data = steamapps / "compatdata" / APP_ID
    config = compat_data / "config_info"
    try:
        lines = [line.strip() for line in config.read_text(encoding="utf-8").splitlines()]
    except OSError as error:
        raise FridaServerError(f"cannot read Proton configuration: {error}") from error
    default_prefix = next(
        (Path(line) for line in lines if line.endswith("/files/share/default_pfx/")),
        None,
    )
    if default_prefix is None:
        raise FridaServerError("Proton configuration does not identify its runtime")
    proton_root = default_prefix.parents[2]
    proton = proton_root / "proton"
    client_root = proton_root.parents[2]
    if not proton.is_file():
        raise FridaServerError(f"Proton launcher is missing: {proton}")
    return proton, client_root, compat_data


def _server_pids(address: str, proc_root: Path = Path("/proc")) -> set[int]:
    marker = SERVER_NAME.encode()
    address_marker = address.encode()
    matches: set[int] = set()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if marker in command and address_marker in command:
            matches.add(int(entry.name))
    return matches


def _port_open(address: str) -> bool:
    host, raw_port = address.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(raw_port)), timeout=0.2):
            return True
    except OSError:
        return False


def _stop_owned_processes(pids: set[int], launcher: subprocess.Popen[bytes]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any((Path("/proc") / str(pid)).exists() for pid in pids):
        time.sleep(0.05)
    for pid in pids:
        if (Path("/proc") / str(pid)).exists():
            os.kill(pid, signal.SIGKILL)
    if launcher.poll() is None:
        launcher.terminate()
        try:
            launcher.wait(timeout=3)
        except subprocess.TimeoutExpired:
            launcher.kill()
            launcher.wait(timeout=3)


@contextmanager
def frida_server_session(
    executable: Path,
    *,
    address: str = DEFAULT_ADDRESS,
    server_path: Path = SERVER_PATH,
) -> Iterator[str]:
    """Start one loopback-only server and remove exactly the processes it owns."""
    if _port_open(address):
        raise FridaServerError(f"Frida server address is already in use: {address}")
    server = verify_server_binary(server_path)
    proton, client_root, compat_data = proton_configuration(executable)
    before = _server_pids(address)
    environment = os.environ.copy()
    environment.update({
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(client_root),
        "STEAM_COMPAT_DATA_PATH": str(compat_data),
        "WINEDEBUG": "-all",
    })
    launcher = subprocess.Popen(
        [str(proton), "run", str(server), "-l", address],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    owned: set[int] = set()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if _port_open(address):
                owned = _server_pids(address) - before
                if not owned:
                    raise FridaServerError("server opened its port but its host process was not identified")
                yield address
                return
            if launcher.poll() is not None:
                raise FridaServerError(f"Windows Frida server exited with status {launcher.returncode}")
            time.sleep(0.1)
        raise FridaServerError("Windows Frida server did not open its loopback port")
    finally:
        owned.update(_server_pids(address) - before)
        _stop_owned_processes(owned, launcher)

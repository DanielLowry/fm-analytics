"""Shared fixtures and HTTP helpers for the web server tests."""

import json
import threading
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.server import SquadWebServer


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "src/fm_analytics/fixtures/sample-game.json"


def write_complete_fixture(directory: Path) -> Path:
    game, squad = load_fixture(FIXTURE)
    original = squad.players[0]
    required = required_role_attributes()
    players = tuple(
        replace(
            original,
            id=f"player-{index}",
            name=f"Player {index}",
            positions=(slot.position,),
            attributes={
                name: AttributeObservation(Visibility.KNOWN, value=10) for name in required
            },
        )
        for index, slot in enumerate(MVP_CATALOGUE.tactics["balanced_442"].slots, start=1)
    )
    complete_squad = replace(squad, players=players)
    path = directory / "complete.json"
    path.write_text(
        json.dumps({"game": game.to_dict(), "squad": complete_squad.to_dict()}),
        encoding="utf-8",
    )
    return path


class WebServerHelpers:
    """Mixin for TestCases that serve a fixture and talk to it over HTTP."""

    def _serve(self, fixture_path: Path, scouting_provider=None, scouting_refresh=None):
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(fixture_path),
            scouting_provider=scouting_provider,
            scouting_refresh=scouting_refresh,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server.server_address[1]

    def _get(self, port: int, path: str) -> tuple[int, str]:
        connection = HTTPConnection("127.0.0.1", port)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, body

    def _post(self, port: int, path: str, body: str = "") -> tuple[int, str | None, str]:
        connection = HTTPConnection("127.0.0.1", port)
        connection.request(
            "POST", path, body,
            {"Content-Type": "application/x-www-form-urlencoded"} if body else {},
        )
        response = connection.getresponse()
        location = response.getheader("Location")
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, location, body

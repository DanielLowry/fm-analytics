import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.domain.models import SquadTeam
from fm_analytics.match_ingest import record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.web.contract_render import contracts_body
from tests.match_support import capture_document, season
from tests.test_contract_planning import (
    CLUB,
    GAME,
    SQUAD_PLAYERS,
    _BASE_SQUAD,
    Fixture,
    contract,
    make_player,
)
from tests.web_support import FIXTURE, WebServerHelpers


def write_squad(directory: Path, *, other_teams=()) -> Path:
    squad = replace(_BASE_SQUAD, club=CLUB, players=SQUAD_PLAYERS, other_teams=other_teams)
    game = replace(GAME, controlled_club=CLUB)
    path = directory / "squad.json"
    path.write_text(json.dumps({"game": game.to_dict(), "squad": squad.to_dict()}), encoding="utf-8")
    return path


class ContractsPageCase(WebServerHelpers, unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        matches = season()
        detailed = next(item for item in matches if item["detail"])
        for line, player in zip(detailed["detail"]["players"][:11], SQUAD_PLAYERS):
            line["playerId"] = player.id
        capture = self.directory / "capture.json"
        capture.write_text(json.dumps(capture_document(matches)), encoding="utf-8")
        self.store = MatchHistoryStore(self.directory / "history.sqlite3")
        record_capture_file(self.store, capture)

    def serve(self, fixture=None, **kwargs) -> int:
        kwargs.setdefault("match_store", self.store)
        return self._serve(fixture or write_squad(self.directory), pinned_tactics=("balanced_442",), **kwargs)


class ContractsPageTests(ContractsPageCase):
    def test_the_page_ranks_who_to_secure_first(self) -> None:
        status, body = self._get(self.serve(), "/contracts")
        self.assertEqual(status, 200)
        self.assertIn('href="/contracts" class="active"', body)
        self.assertIn("4 of your 11 recommended starters could leave within six months", body)
        self.assertIn("Who to act on, in order", body)
        self.assertIn("id='verdict-secure_now'", body)
        # Ranked: the any-day striker before the winger whose contract ends soon.
        self.assertLess(body.index("/squad/player/st1"), body.index("/squad/player/ml"))
        self.assertIn("Only cover at GK", body)
        self.assertIn("When players could leave", body)
        self.assertIn("How verdicts are decided", body)
        self.assertIn("6.80", body)  # the recorded competitive rating, joined on FM ID

    def test_the_player_report_shows_the_same_plan(self) -> None:
        status, body = self._get(self.serve(), "/squad/player/gk")
        self.assertEqual(status, 200)
        self.assertIn("Contract plan", body)
        self.assertIn("Secure now", body)
        self.assertIn("Hard to replace: GK2", body)

    def test_without_history_the_page_says_why_form_is_missing(self) -> None:
        status, body = self._get(self.serve(match_store=None), "/contracts")
        self.assertEqual(status, 200)
        self.assertIn("No match history is recorded", body)

    def test_a_bad_scope_is_refused(self) -> None:
        status, _body = self._get(self.serve(), "/contracts?team=bogus")
        self.assertEqual(status, 400)

    def test_other_club_squads_are_offered_and_shown_on_request(self) -> None:
        youth = make_player("youth", "ST", 11, contract("non_contract", None), age=18)
        fixture = write_squad(self.directory, other_teams=(SquadTeam(marker=2, players=(youth,)),))
        port = self.serve(fixture)
        _status, first = self._get(port, "/contracts")
        self.assertIn("All club squads", first)
        self.assertNotIn("/squad/player/youth", first)
        _status, everyone = self._get(port, "/contracts?team=all")
        self.assertIn("/squad/player/youth", everyone)
        self.assertIn("Other squad", everyone)

    def test_an_unscoreable_squad_fails_the_page_but_not_the_player_report(self) -> None:
        port = self.serve(FIXTURE)
        status, _body = self._get(port, "/contracts")
        self.assertEqual(status, 503)
        status, body = self._get(port, "/squad/player/player-1")
        self.assertEqual(status, 200)
        self.assertNotIn("Contract plan", body)


class ContractRenderTests(unittest.TestCase):
    def test_let_go_keeps_the_barely_used_folded_away(self) -> None:
        body = contracts_body(Fixture.review())
        let_go = body[body.index("id='verdict-let_go'"):]
        folded = let_go.index("class='fm-contract-unused'")
        self.assertLess(let_go.index("/squad/player/dc3"), folded)  # played poorly
        self.assertGreater(let_go.index("/squad/player/dc4"), folded)  # never played

    def test_player_names_are_escaped(self) -> None:
        review = Fixture.review()
        first = replace(review.assessments[0], player_name="<script>alert(1)</script>")
        body = contracts_body(replace(review, assessments=(first, *review.assessments[1:])))
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)


if __name__ == "__main__":
    unittest.main()

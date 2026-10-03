import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from fm_analytics.analytics.contract_planning import (
    ContractRisk,
    FormBand,
    PositionLevel,
    Value,
    Verdict,
    add_months,
    assess_contracts,
    classify_value,
    contract_risk,
    months_between,
    verdict_for,
)
from fm_analytics.analytics.match_players import PlayerRating, PlayerSeason
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Club, PlayerContract, Visibility
from fm_analytics.domain.models import SquadTeam
from fm_analytics.match_ingest import record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import (
    RecommendationPolicy,
    build_contract_review,
    build_player_role_scores,
    build_recommendation_bundle,
    required_role_attributes,
)
from tests.match_support import FRIENDLY, US, capture_document, detail, lineup, match, season
from tests.web_support import FIXTURE

CLUB = Club(US["id"], US["name"])
ELSEWHERE = Club("999", "Elsewhere United")
GAME, _BASE_SQUAD = load_fixture(FIXTURE)
TODAY = GAME.game_date
ENDS_SOON = add_months(TODAY, 3)
NEXT_YEAR = add_months(TODAY, 12)
SETTLED = add_months(TODAY, 36)


def contract(kind: str = "full_time", end: date | None = SETTLED, *, owner: Club = CLUB, joined=None):
    return PlayerContract(kind, None, end, joined, None, None, owner)


def make_player(player_id: str, position: str, level: int, deal: PlayerContract | None, *, age: int = 25):
    base = _BASE_SQUAD.players[0]
    return replace(
        base,
        id=player_id,
        name=player_id.upper(),
        age=age,
        positions=(position,),
        position_familiarity={position: 20},
        club_id=CLUB.id,
        condition_percent=100,
        match_fitness_percent=100,
        availability="available",
        injured=False,
        suspended=False,
        contract=deal,
        attributes={name: AttributeObservation(Visibility.KNOWN, value=level) for name in required_role_attributes()},
    )


# Eleven equal starters for a pinned balanced 4-4-2, then chosen backups: the
# goalkeeper's only cover is poor, the right-back's cover is close, and the
# centre-backs have two weak covers between them.
SQUAD_PLAYERS = (
    make_player("gk", "GK", 14, contract(end=ENDS_SOON)),
    make_player("gk2", "GK", 4, contract(end=ENDS_SOON), age=17),
    make_player("dl", "DL", 12, contract()),
    make_player("dc1", "DC", 12, contract()),
    make_player("dc2", "DC", 12, contract()),
    make_player("dc3", "DC", 6, contract("non_contract", None)),
    make_player("dc4", "DC", 7, contract(end=ENDS_SOON)),
    make_player("dr", "DR", 12, contract("non_contract", None)),
    make_player("dr2", "DR", 11, contract()),
    make_player("ml", "ML", 12, contract(end=ENDS_SOON)),
    make_player("mc1", "MC", 12, contract(end=NEXT_YEAR)),
    make_player("mc2", "MC", 12, contract()),
    make_player("mr", "MR", 12, contract()),
    make_player("st1", "ST", 12, contract("non_contract", None), age=19),
    make_player("st2", "ST", 12, contract()),
    make_player("amc", "AMC", 14, contract("non_contract", None)),  # no AMC slot in a 4-4-2
    make_player("loan", "MC", 9, contract(end=SETTLED, owner=ELSEWHERE)),
    make_player("unknown", "MR", 9, None),
)

RATINGS = {
    "gk": 6.6, "dl": 6.5, "dc1": 6.9, "dc2": 6.7, "dc3": 6.3, "dr": 6.4,
    "ml": 7.2, "mc1": 7.0, "mc2": 6.6, "mr": 6.8, "st1": 7.4, "st2": 6.5,
}


def player_season(player_id: str, rating: float, minutes: int = 900) -> PlayerSeason:
    matches = max(1, minutes // 90)
    return PlayerSeason(
        name=player_id.upper(), player_id=player_id, appearances=matches, starts=matches,
        minutes=minutes, distance_m=0, stats={}, roles=(),
        ratings=tuple(PlayerRating(TODAY, "Opponent", rating) for _ in range(matches)),
    )


SEASONS = {key: player_season(key, value) for key, value in RATINGS.items()}
SEASONS["loan"] = player_season("loan", 8.0, minutes=300)  # too few minutes to count


class Fixture:
    _bundle = None

    @classmethod
    def bundle(cls):
        if cls._bundle is None:
            squad = replace(_BASE_SQUAD, club=CLUB, players=SQUAD_PLAYERS)
            game = replace(GAME, controlled_club=CLUB)
            cls._bundle = build_recommendation_bundle(
                game, squad, policy=RecommendationPolicy(pinned_tactics=("balanced_442",))
            )
        return cls._bundle

    @classmethod
    def review(cls, seasons=SEASONS, other_players=()):
        bundle = cls.bundle()
        players = bundle.squad.players
        return assess_contracts(
            players,
            other_players=other_players,
            game_date=TODAY,
            club_id=CLUB.id,
            seasons=seasons,
            position_fits={
                player.id: build_player_role_scores(player, bundle.role_matrix).in_position
                for player in (*players, *other_players)
            },
            weakness_report=bundle.weakness_report,
            tactic_name=bundle.primary.tactic.name,
        )


class DateTests(unittest.TestCase):
    def test_add_months_clamps_to_the_end_of_a_short_month(self):
        self.assertEqual(add_months(date(2020, 1, 31), 1), date(2020, 2, 29))
        self.assertEqual(add_months(date(2019, 8, 31), 6), date(2020, 2, 29))
        self.assertEqual(add_months(date(2020, 11, 15), 18), date(2022, 5, 15))

    def test_months_between_counts_whole_months(self):
        self.assertEqual(months_between(date(2020, 2, 5), date(2020, 6, 30)), 4)
        self.assertEqual(months_between(date(2020, 2, 5), date(2020, 3, 4)), 0)
        self.assertEqual(months_between(date(2020, 2, 5), date(2020, 1, 5)), -1)


class ContractRiskTests(unittest.TestCase):
    def risk(self, deal):
        return contract_risk(make_player("p", "DC", 10, deal), TODAY, CLUB.id)

    def test_non_contract_can_leave_any_day(self):
        self.assertIs(self.risk(contract("non_contract", None)), ContractRisk.ANY_DAY)

    def test_windows_include_their_last_day(self):
        self.assertIs(self.risk(contract(end=add_months(TODAY, 6))), ContractRisk.ENDS_SOON)
        self.assertIs(self.risk(contract(end=add_months(TODAY, 6) + timedelta(days=1))), ContractRisk.NEXT_YEAR)
        self.assertIs(self.risk(contract(end=add_months(TODAY, 18))), ContractRisk.NEXT_YEAR)
        self.assertIs(self.risk(contract(end=add_months(TODAY, 19))), ContractRisk.SETTLED)

    def test_an_expired_contract_is_still_urgent(self):
        self.assertIs(self.risk(contract(end=add_months(TODAY, -1))), ContractRisk.ENDS_SOON)

    def test_loan_unknown_and_undated_contracts(self):
        self.assertIs(self.risk(contract(owner=ELSEWHERE)), ContractRisk.ON_LOAN)
        self.assertIs(self.risk(None), ContractRisk.UNKNOWN)
        self.assertIs(self.risk(contract("full_time", None)), ContractRisk.UNKNOWN)


class VerdictRuleTests(unittest.TestCase):
    def test_the_verdict_matrix_cell_by_cell(self):
        expected = {
            (Value.CORE, ContractRisk.ANY_DAY): Verdict.SECURE_NOW,
            (Value.CORE, ContractRisk.ENDS_SOON): Verdict.SECURE_NOW,
            (Value.CORE, ContractRisk.NEXT_YEAR): Verdict.RENEW_EARLY,
            (Value.CORE, ContractRisk.SETTLED): Verdict.SETTLED,
            (Value.USEFUL, ContractRisk.ENDS_SOON): Verdict.KEEP_IF_TERMS,
            (Value.USEFUL, ContractRisk.NEXT_YEAR): Verdict.REVIEW_LATER,
            (Value.USEFUL, ContractRisk.SETTLED): Verdict.SETTLED,
            (Value.UNPROVEN, ContractRisk.ANY_DAY): Verdict.YOUR_CALL,
            (Value.UNPROVEN, ContractRisk.NEXT_YEAR): Verdict.REVIEW_LATER,
            (Value.MARGINAL, ContractRisk.ANY_DAY): Verdict.LET_GO,
            (Value.MARGINAL, ContractRisk.NEXT_YEAR): Verdict.LET_RUN_DOWN,
            (Value.MARGINAL, ContractRisk.SETTLED): Verdict.SURPLUS,
            (Value.CORE, ContractRisk.ON_LOAN): Verdict.ON_LOAN,
            (Value.CORE, ContractRisk.UNKNOWN): Verdict.UNKNOWN,
        }
        for (value, risk), verdict in expected.items():
            with self.subTest(value=value, risk=risk):
                self.assertIs(verdict_for(value, risk), verdict)

    def test_value_needs_both_readings_or_a_hard_to_replace_starter(self):
        S, Q, B = PositionLevel.STARTER, PositionLevel.SQUAD, PositionLevel.BELOW
        cases = (
            (FormBand.STRONG, Q, False, False, Value.CORE),
            (FormBand.SOLID, S, False, False, Value.CORE),
            (FormBand.POOR, B, True, True, Value.CORE),  # hard to replace
            (FormBand.STRONG, B, False, False, Value.USEFUL),  # form and score disagree
            (FormBand.POOR, S, True, False, Value.USEFUL),  # a starter in poor form
            (FormBand.POOR, S, False, False, Value.MARGINAL),
            (FormBand.SOLID, B, False, False, Value.MARGINAL),
            (FormBand.NO_EVIDENCE, S, False, False, Value.UNPROVEN),
            (FormBand.NO_EVIDENCE, Q, True, False, Value.UNPROVEN),
            (FormBand.NO_EVIDENCE, Q, False, False, Value.MARGINAL),
        )
        for form, level, in_xi, hard, value in cases:
            with self.subTest(form=form, level=level, in_xi=in_xi, hard=hard):
                self.assertIs(classify_value(form, level, in_xi=in_xi, hard_to_replace=hard), value)


class AssessContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = Fixture.bundle()
        cls.review = Fixture.review()
        cls.by_id = {item.player_id: item for item in cls.review.assessments}

    def test_form_thirds_come_from_rated_first_team_players_only(self):
        self.assertEqual(self.review.rated_players, 12)
        self.assertEqual((self.review.poor_below, self.review.strong_from), (6.6, 6.9))
        self.assertIs(self.by_id["loan"].form, FormBand.NO_EVIDENCE)  # 8.0 over 300 minutes
        self.assertEqual(self.by_id["st1"].form_rank, 1)
        self.assertIs(self.by_id["mr"].form, FormBand.SOLID)
        self.assertIs(self.by_id["dl"].form, FormBand.POOR)

    def test_the_request_strong_form_and_score_with_an_expiring_contract_is_secured_first(self):
        first = self.review.assessments[0]
        self.assertEqual(first.player_id, "st1")
        self.assertIs(first.verdict, Verdict.SECURE_NOW)
        self.assertIs(first.risk, ContractRisk.ANY_DAY)
        self.assertIs(self.by_id["ml"].verdict, Verdict.SECURE_NOW)
        self.assertIs(self.by_id["mc1"].verdict, Verdict.RENEW_EARLY)

    def test_any_day_players_come_first_within_a_verdict(self):
        secure = [item.player_id for item in self.review.with_verdict(Verdict.SECURE_NOW)]
        self.assertEqual(secure[0], "st1")
        self.assertEqual(set(secure), {"st1", "ml", "gk"})

    def test_a_poorly_rated_starter_with_close_cover_is_kept_on_terms(self):
        item = self.by_id["dr"]
        self.assertTrue(item.in_xi)
        self.assertFalse(item.hard_to_replace)
        self.assertIs(item.verdict, Verdict.KEEP_IF_TERMS)
        self.assertIn("Form and position score disagree", [reason.label for reason in item.reasons])

    def test_a_weak_only_cover_makes_the_starter_hard_to_replace_and_himself_replace_first(self):
        keeper, backup = self.by_id["gk"], self.by_id["gk2"]
        self.assertTrue(keeper.hard_to_replace)
        self.assertEqual(keeper.cover_name, "GK2")
        self.assertIs(backup.verdict, Verdict.REPLACE_FIRST)
        self.assertEqual(backup.only_cover_for, ("GK",))
        self.assertIn("only cover at GK", backup.advice)

    def test_marginal_players_are_let_go_and_surplus_keeps_its_verdict(self):
        self.assertIs(self.by_id["dc3"].verdict, Verdict.LET_GO)  # played poorly, not in the XI
        self.assertIs(self.by_id["dc4"].verdict, Verdict.LET_GO)  # unused and below squad level
        self.assertEqual(self.by_id["dr2"].only_cover_for, ("DR",))
        self.assertIs(self.by_id["dr2"].verdict, Verdict.SURPLUS)  # settled: no decision to override

    def test_unproven_loan_and_unknown(self):
        amc = self.by_id["amc"]
        self.assertIs(amc.level, PositionLevel.STARTER)
        self.assertFalse(amc.in_xi)
        self.assertIs(amc.verdict, Verdict.YOUR_CALL)
        self.assertIs(self.by_id["loan"].verdict, Verdict.ON_LOAN)
        self.assertIs(self.by_id["unknown"].verdict, Verdict.UNKNOWN)

    def test_numbers_match_the_squad_and_depth_pages(self):
        depth = {slot.starter.player_id: slot for slot in self.bundle.weakness_report.depth if slot.starter}
        for player in self.bundle.squad.players:
            item = self.by_id[player.id]
            in_position = build_player_role_scores(player, self.bundle.role_matrix).in_position
            self.assertEqual(item.position_score, in_position.position_adjusted_score.central)
            if player.id in depth:
                slot = depth[player.id]
                self.assertEqual(item.starter_score, slot.starter.tapered_attribute_score.central)
                cover = slot.available_backups[0] if slot.available_backups else None
                self.assertEqual(item.cover_score, cover.role_score.score.central if cover else None)
        self.assertEqual(len(self.review.xi), 11)

    def test_starters_who_could_leave_within_six_months(self):
        self.assertEqual({item.player_id for item in self.review.xi_at_risk}, {"st1", "ml", "gk", "dr"})

    def test_keep_value_is_bounded_and_rewards_youth(self):
        self.assertTrue(all(0 <= item.keep_value <= 100 for item in self.review.assessments))
        self.assertIn("21 or under", [reason.label for reason in self.by_id["st1"].reasons])

    def test_other_squads_never_move_first_team_verdicts(self):
        youth = make_player("youth", "ST", 11, contract("non_contract", None), age=18)
        widened = Fixture.review(other_players=(youth,))
        self.assertEqual((widened.poor_below, widened.strong_from), (self.review.poor_below, self.review.strong_from))
        for item in self.review.assessments:
            other = widened.for_player(item.player_id)
            self.assertEqual((other.verdict, other.keep_value), (item.verdict, item.keep_value))
        added = widened.for_player("youth")
        self.assertFalse(added.first_team)
        self.assertFalse(added.in_xi)

    def test_without_match_evidence_verdicts_rest_on_contracts_and_attributes(self):
        review = Fixture.review(seasons={})
        self.assertIsNone(review.strong_from)
        self.assertTrue(all(item.form is FormBand.NO_EVIDENCE for item in review.assessments))
        self.assertIs(review.for_player("gk").verdict, Verdict.SECURE_NOW)  # still hard to replace


class BuildContractReviewTests(unittest.TestCase):
    """The reporting entry point: competitive ratings in the last year, joined on FM ID."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        matches = season()
        detailed = next(item for item in matches if item["detail"])
        ours = detailed["detail"]["players"][:11]
        for line, player in zip(ours, SQUAD_PLAYERS):
            line["playerId"] = player.id
        friendly_lineup = lineup("home")
        for line, player in zip(friendly_lineup, SQUAD_PLAYERS):
            line["playerId"], line["rating"] = player.id, 9.9
        matches[0] = match("2019-07-20", US, matches[0]["away"], 5, 0, competition=FRIENDLY,
                           detail=detail(players=friendly_lineup))
        capture = Path(directory.name) / "capture.json"
        capture.write_text(json.dumps(capture_document(matches)), encoding="utf-8")
        store = MatchHistoryStore(Path(directory.name) / "history.sqlite3")
        record_capture_file(store, capture)
        self.history = store.load_history(store.latest_save_key())

    def test_competitive_ratings_join_on_player_id_and_friendlies_are_left_out(self):
        review = build_contract_review(Fixture.bundle(), self.history)
        keeper = review.for_player("gk")
        self.assertIsNone(review.history_note)
        self.assertEqual(keeper.average_rating, 6.8)  # the friendly's 9.9 is not counted
        self.assertEqual(keeper.minutes, 90)
        self.assertIs(keeper.form, FormBand.NO_EVIDENCE)

    def test_matches_more_than_a_year_old_are_left_out(self):
        bundle = Fixture.bundle()
        later = replace(bundle, game=replace(bundle.game, game_date=date(2020, 9, 5)))
        review = build_contract_review(later, self.history)
        self.assertIsNone(review.for_player("gk").average_rating)
        self.assertIn("No competitive match", review.history_note)

    def test_another_clubs_history_is_not_used(self):
        bundle = Fixture.bundle()
        squad = replace(bundle.squad, club=ELSEWHERE)
        review = build_contract_review(replace(bundle, squad=squad), self.history)
        self.assertIn("not used for form", review.history_note)
        self.assertIsNone(review.for_player("gk").average_rating)

    def test_no_history_is_explained(self):
        review = build_contract_review(Fixture.bundle(), None)
        self.assertIn("No match history is recorded", review.history_note)

    def test_other_squads_are_included_on_request(self):
        bundle = Fixture.bundle()
        youth = make_player("youth", "ST", 11, contract("non_contract", None), age=18)
        squad = replace(bundle.squad, other_teams=(SquadTeam(marker=2, players=(youth,)),))
        widened = replace(bundle, squad=squad)
        self.assertIsNone(build_contract_review(widened, None).for_player("youth"))
        self.assertIsNotNone(build_contract_review(widened, None, include_other_squads=True).for_player("youth"))


if __name__ == "__main__":
    unittest.main()

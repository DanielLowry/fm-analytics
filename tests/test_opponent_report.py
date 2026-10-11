"""The opponent report: who scores and supplies, how goals come, their shape and the suggested instructions."""

from __future__ import annotations

import json
import unittest
from datetime import date

from fm_analytics.analytics.opponent_report import (
    DEFAULT_WINDOW,
    build_opponent_report,
    next_fixture,
)
from fm_analytics.domain.matches import MatchRecord, ScheduledFixture, TeamRef
from fm_analytics.domain.models import Player
from fm_analytics.opponent_export import opponent_document
from fm_analytics.persistence.match_history import MatchHistory
from fm_analytics.reporting import build_opponent_export, opponent_choices
from fm_analytics.reporting import build_opponent_report as report_on

from tests.match_support import ALPHA, BRAVO, CHARLIE, LEAGUE, US, team_stats

# 4-4-2 as FM's line-up list runs: (position, centre side).
SHAPE = (("GK", None), ("DR", None), ("DC", "right"), ("DC", "left"), ("DL", None), ("MR", None),
         ("MC", "right"), ("MC", "left"), ("ML", None), ("ST", "right"), ("ST", "left"))
GK, DR, DCR, DCL, DL, MR, MCR, MCL, ML, STR, STL = range(11)
HEADER_FROM_CROSS = "0240000001000000"  # a header in the six-yard box, from a cross
SHOT_IN_AREA = "0000000002000000"
FREE_KICK = "0008000000000000"


def short_id(club: dict, order: int) -> int:
    return int(club["id"]) * 100 + order


def players(club: dict, side: str, *, stats: dict[int, dict] | None = None) -> list[dict]:
    stats = stats or {}
    return [
        {
            "side": side, "order": order, "started": True, "shortId": short_id(club, order),
            "playerId": str(short_id(club, order)), "name": f"{club['name']} {position}{order}", "shirt": order + 1,
            "roleCode": 0x80, "played": True, "rating": 7.0, "stats": stats.get(order, {}),
            "cameOn": None, "wentOff": None, "position": position, "startPosition": position,
            **({"startCentreSide": centre} if centre else {}),
        }
        for order, (position, centre) in enumerate(SHAPE)
    ]


def goal(minute: int, side: str, club: dict, scorer: int, *, assist: int | None = None,
         descriptor: str = SHOT_IN_AREA, kind: str = "goal") -> list[dict]:
    events = [{"minute": minute, "side": side, "kind": kind, "code": 1, "playerShortId": short_id(club, scorer),
               "descriptor": descriptor}]
    if assist is not None:
        events.append({"minute": minute, "side": side, "kind": "assist", "code": 0x24,
                       "playerShortId": short_id(club, assist)})
    return events


def game(day: str, home: dict, away: dict, *, events=(), home_stats=None, away_stats=None,
         formations=None, competition=LEAGUE) -> MatchRecord:
    home_goals = sum(1 for e in events if e["kind"] in ("goal", "penalty") and e["side"] == "home") + sum(
        1 for e in events if e["kind"] == "own_goal" and e["side"] == "away")
    away_goals = sum(1 for e in events if e["kind"] in ("goal", "penalty") and e["side"] == "away") + sum(
        1 for e in events if e["kind"] == "own_goal" and e["side"] == "home")
    detail = {
        "home": team_stats(goals=home_goals), "away": team_stats(goals=away_goals),
        "players": players(home, "home", stats=home_stats) + players(away, "away", stats=away_stats),
        "events": list(events),
    }
    if formations:
        detail["formations"] = formations
    return MatchRecord.from_document({
        "date": day, "competition": competition, "home": home, "away": away, "homeGoals": home_goals,
        "awayGoals": away_goals, "attendance": 400, "detail": detail, "season": 2019,
    })


def alpha_season() -> list[MatchRecord]:
    """Alpha's striker (left of the pair) heads three crosses from their right midfielder."""
    return [
        game("2019-08-03", ALPHA, BRAVO, events=goal(20, "home", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS),
             formations={"home": "4-4-2", "away": "4-2-3-1 Wide"}, home_stats={MR: {"dribbles": 9}}),
        game("2019-08-10", CHARLIE, ALPHA, events=goal(55, "away", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS)
             + goal(80, "home", CHARLIE, STR, assist=MR, descriptor=HEADER_FROM_CROSS),
             formations={"away": "4-4-2"}, away_stats={MR: {"dribbles": 9}}),
        game("2019-08-17", ALPHA, CHARLIE, events=goal(70, "home", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS)
             + goal(85, "home", ALPHA, MCR, descriptor=FREE_KICK),
             formations={"home": "4-1-4-1 DM Wide"}, home_stats={MR: {"dribbles": 9}}),
    ]


def roster_player(order: int, *, foot: str | None = None, **attributes: tuple[int, int]) -> Player:
    return Player.from_dict({
        "id": str(short_id(ALPHA, order)), "name": f"Alpha {order}", "dateOfBirth": None, "age": 25,
        "positions": ["ST"], "clubId": ALPHA["id"], "conditionPercent": None, "matchFitnessPercent": None,
        "availability": "unknown", "injured": None, "suspended": None, "contract": None,
        "preferredFoot": foot,
        "attributes": {name: {"visibility": "range", "minimum": low, "maximum": high}
                       for name, (low, high) in attributes.items()},
    })


def report(matches=None, **options):
    return build_opponent_report(
        TeamRef(ALPHA["id"], ALPHA["name"]), our_club_id=US["id"], our_matches=options.pop("ours", ()),
        club_matches=alpha_season() if matches is None else matches, **options,
    )


class FinishersAndSuppliersTests(unittest.TestCase):
    def test_the_striker_finishes_and_the_right_midfielder_supplies_from_crosses(self) -> None:
        found = report()
        striker, supplier = found.finishers[0], found.suppliers[0]
        self.assertEqual((striker.position, striker.side, striker.goals, striker.headed_goals, striker.goals_from_crosses),
                         ("ST", "left", 3, 3, 3))
        self.assertEqual((supplier.position, supplier.assists, supplier.assists_from_crosses), ("MR", 3, 3))
        self.assertEqual([(pair.supplier, pair.scorer, pair.goals) for pair in found.partnerships],
                         [("Alpha MR5", "Alpha ST10", 3)])
        self.assertEqual((found.goals_for, found.goals_against, found.evidence.matches), (4, 1, 3))

    def test_how_they_score_counts_headers_from_crosses_by_flank_and_the_far_side_guess(self) -> None:
        scored = report().scored
        self.assertEqual(scored.row("header_from_cross").goals, 3)
        self.assertEqual(scored.row("direct_free_kick").goals, 1)
        self.assertEqual(scored.row("right").goals, 3)  # crosses came down their right
        self.assertEqual((scored.far_side, scored.flank_crosses), (3, 3))  # the left striker met them
        self.assertEqual(scored.row("strikers").goals, 3)
        self.assertEqual(scored.row("six_yard_box").goals, 3)

    def test_a_cross_they_conceded_from_the_attackers_right_came_down_their_left(self) -> None:
        conceded = report().conceded
        self.assertEqual((conceded.goals, conceded.row("left").goals, conceded.row("right").goals), (1, 1, 0))

    def test_a_cross_from_a_player_who_took_corners_is_a_guess_kept_out_of_the_flanks(self) -> None:
        matches = [
            game("2019-08-03", ALPHA, BRAVO, events=goal(20, "home", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS),
                 home_stats={MR: {"corners_taken": 3}}),
        ]
        scored = report(matches).scored
        self.assertEqual((scored.row("possibly_corner").goals, scored.row("header_from_cross").goals), (1, 0))
        self.assertEqual(sum(row.goals for row in scored.cross_flanks), 0)
        self.assertTrue(scored.row("possibly_corner").guess)
        self.assertIsNone(scored.row("possibly_corner").luck)

    def test_an_own_goal_is_never_called_a_pattern(self) -> None:
        own_goal = [{"minute": 30, "side": "away", "kind": "own_goal", "code": 2, "playerShortId": short_id(BRAVO, DCL)}]
        matches = [game(f"2019-08-{day:02d}", ALPHA, BRAVO, events=own_goal) for day in range(3, 30, 7)]
        row = report(matches).scored.row("own_goal")
        self.assertEqual(row.goals, 4)
        self.assertIsNone(row.pattern)


class EvidenceTests(unittest.TestCase):
    def test_nothing_played_on_or_after_the_report_date_is_used(self) -> None:
        found = report(as_of=date(2019, 8, 17))
        self.assertEqual((found.evidence.matches, found.evidence.last, found.goals_for), (2, date(2019, 8, 10), 2))

    def test_the_window_takes_their_latest_matches_and_must_be_a_known_size(self) -> None:
        self.assertEqual(report().evidence.window, DEFAULT_WINDOW)
        with self.assertRaises(ValueError):
            report(window=7)

    def test_formations_count_each_named_shape_and_the_last_five(self) -> None:
        formations = report().formations
        self.assertEqual([(use.name, use.matches, use.home, use.away) for use in formations.uses],
                         [("4-4-2", 2, 1, 1), ("4-1-4-1 DM Wide", 1, 1, 0)])
        self.assertEqual(formations.recent, ("4-1-4-1 DM Wide", "4-4-2", "4-4-2"))
        self.assertEqual(formations.known, 3)

    def test_the_likely_xi_is_their_eleven_most_recent_starters_in_fms_position_order(self) -> None:
        xi = report().likely_xi
        self.assertEqual([line.position for line in xi],
                         ["GK", "DR", "DC", "DC", "DL", "MR", "MC", "MC", "ML", "ST", "ST"])
        self.assertTrue(all(line.recent_starts == 3 for line in xi))

    def test_meetings_with_us_come_from_our_own_record(self) -> None:
        ours = [game("2019-08-24", US, ALPHA, events=goal(10, "away", ALPHA, STL), formations={"away": "4-4-2"})]
        found = report(ours=ours)
        self.assertEqual([(m.venue, m.our_goals, m.their_goals, m.their_formation) for m in found.meetings],
                         [("H", 0, 1, "4-4-2")])
        self.assertEqual((found.evidence.against_us, found.formations.against_us), (1, "4-4-2"))


class InstructionTests(unittest.TestCase):
    def test_their_goal_threat_is_marked_tight_and_mostly_headers_say_so(self) -> None:
        striker = report().instructions[0]
        self.assertEqual((striker.player, striker.marking, striker.show_onto), ("Alpha ST10", "Tight", None))
        self.assertIn("were headers", " ".join(striker.reasons))

    def test_a_wide_supplier_is_closed_down_and_their_dribbler_eased_off(self) -> None:
        supplier = next(item for item in report().instructions if item.position == "MR")
        self.assertEqual((supplier.closing_down, supplier.tackling, supplier.show_onto), ("More", "Ease off", "Weaker foot"))

    def test_a_supplier_of_crosses_that_may_have_been_his_corners_is_left_alone(self) -> None:
        matches = [
            game(f"2019-08-{day:02d}", ALPHA, BRAVO, events=goal(20, "home", ALPHA, STL, assist=MCR, descriptor=HEADER_FROM_CROSS),
                 home_stats={MCR: {"corners_taken": 4}})
            for day in (3, 10, 17)
        ]
        self.assertNotIn("MC", [item.position for item in report(matches).instructions])

    def test_what_fm_shows_of_a_player_adds_pressing_but_never_on_a_striker_or_a_two_footed_show(self) -> None:
        roster = [roster_player(DCL, composure=(4, 7)), roster_player(STL, foot="Either", composure=(5, 8))]
        instructions = report(roster=roster).instructions
        centre_back = next(item for item in instructions if item.position == "DC")
        self.assertEqual((centre_back.closing_down, centre_back.tackling), ("Always", "Get stuck in"))
        self.assertIn("composure 4-7", " ".join(centre_back.reasons))
        striker = next(item for item in instructions if item.position == "ST")
        self.assertEqual((striker.closing_down, striker.tackling, striker.show_onto), (None, "Get stuck in", None))

    def test_an_attribute_fm_does_not_show_for_certain_adds_nothing(self) -> None:
        roster = [roster_player(DCL, composure=(6, 12))]
        self.assertNotIn("DC", [item.position for item in report(roster=roster).instructions])


class FixtureTests(unittest.TestCase):
    def fixtures(self):
        def fixture(day, home, away):
            return ScheduledFixture.from_document({"date": day, "competition": LEAGUE, "home": home, "away": away})
        return (fixture("2019-09-01", US, BRAVO), fixture("2019-09-08", ALPHA, US), fixture("2019-09-15", US, CHARLIE))

    def test_the_next_fixture_is_the_first_on_or_after_the_day_not_already_played(self) -> None:
        played = [game("2019-09-01", US, BRAVO)]
        found = next_fixture(self.fixtures(), US["id"], played, date(2019, 9, 1))
        self.assertEqual((found.date, found.opponent_of(US["id"]).name), (date(2019, 9, 8), "Alpha"))
        self.assertIsNone(next_fixture(self.fixtures(), US["id"], [], date(2019, 9, 16)))

    def history(self) -> MatchHistory:
        from fm_analytics.domain.matches import Competition, LeagueResult
        results = tuple(
            LeagueResult(date(2019, 8, day), TeamRef(home["id"], home["name"]), TeamRef(away["id"], away["name"]), 1, 0, 2019)
            for day, home, away in ((3, ALPHA, BRAVO), (3, US, CHARLIE), (10, CHARLIE, ALPHA), (10, BRAVO, US))
        )
        return MatchHistory(
            save_key="club:100", club=TeamRef(US["id"], US["name"]), matches=(),
            league_results=((Competition(LEAGUE["id"], LEAGUE["name"], LEAGUE["shortName"]), results),),
            notes={}, role_codes={}, last_game_date=date(2019, 9, 2),
        )

    def test_the_report_without_a_club_is_on_the_next_opponent_using_only_matches_before_it(self) -> None:
        later = game("2019-09-10", ALPHA, BRAVO, events=goal(5, "home", ALPHA, STL))
        found = report_on(self.history(), alpha_season() + [later], fixtures=(date(2019, 9, 2), self.fixtures()))
        self.assertEqual((found.club.name, found.fixture.date, found.as_of), ("Alpha", date(2019, 9, 8), date(2019, 9, 8)))
        self.assertEqual(found.evidence.matches, 3)
        self.assertEqual(found.league_position.teams, 4)

    def test_choices_put_the_next_opponent_first_and_an_unknown_club_is_refused(self) -> None:
        history = self.history()
        choices = opponent_choices(history, (date(2019, 9, 2), self.fixtures()))
        self.assertEqual([choice.club.name for choice in choices], ["Alpha", "Charlie", "Bravo"])
        self.assertIsNone(report_on(history, alpha_season()))
        with self.assertRaises(ValueError):
            report_on(history, alpha_season(), club_id="999")

    def test_the_export_is_json_with_every_section_the_page_shows(self) -> None:
        found = report_on(self.history(), alpha_season(), club_id=ALPHA["id"])
        document = json.loads(json.dumps(build_opponent_export(found)))
        self.assertEqual(document, json.loads(json.dumps(opponent_document(found, generated_at=None) | {
            "generated_at": document["generated_at"]})))
        for key in ("formations", "likely_xi", "finishers", "suppliers", "scored", "conceded", "style",
                    "opposition_instructions", "watch", "guesses"):
            self.assertIn(key, document)
        self.assertEqual(document["club"]["name"], "Alpha")


if __name__ == "__main__":
    unittest.main()

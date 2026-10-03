import unittest
from datetime import date, timedelta

from fm_analytics.analytics.appearance_context import FROM_TACTIC, LINE_UP, NO_RATING, AppearanceContext
from fm_analytics.analytics.player_form import FormPolicy, build_form
from fm_analytics.domain.matches import Competition, MatchRecord, PlayerMatchStats, TeamRef

AS_OF = date(2020, 3, 30)
LEAGUE = Competition("148", "Vanarama National League South")


def appearance(days_ago, rating, *, minutes=90, player_id="28106293", tactic="vertical_442", position="ST",
               role="af_attack", usable=True) -> AppearanceContext:
    day = AS_OF - timedelta(days=days_ago)
    match = MatchRecord(day, LEAGUE, TeamRef("5103652", "Hungerford Town"), TeamRef(str(1000 + days_ago), "Them"), 1, 1)
    player = PlayerMatchStats(
        side="home", order=10, started=True, short_id=94381, player_id=player_id, name="Victor Fundi", shirt=10,
        role_code=0x800, played=True, rating=rating, stats={}, went_off=minutes if minutes < 90 else None,
        position=position, start_position=position,
    )
    return AppearanceContext(match, player, tactic, LINE_UP, "Advanced Forward", "STR", role, FROM_TACTIC,
                             () if usable else (NO_RATING,))


class FormTests(unittest.TestCase):
    def test_one_full_match_moves_the_score_a_little(self) -> None:
        # Confidence 1 / (1 + 3) = 0.25; 0.02 x (6.0 - 6.7) = -1.4%; so -0.35%.
        form = build_form([appearance(3, 6.0)], as_of=AS_OF)
        self.assertAlmostEqual(form.multiplier("28106293", "vertical_442", "ST", "af_attack"), 0.9965)

    def test_no_ratings_or_a_disabled_policy_is_exactly_no_change(self) -> None:
        self.assertEqual(build_form([], as_of=AS_OF).multiplier("28106293", "vertical_442", "ST", "af_attack"), 1.0)
        disabled = build_form([appearance(3, 6.0)], as_of=AS_OF, policy=FormPolicy(enabled=False))
        self.assertEqual(disabled.multiplier("28106293", "vertical_442", "ST", "af_attack"), 1.0)

    def test_form_counts_only_in_the_exact_job_it_was_earned_in(self) -> None:
        form = build_form([appearance(3, 5.5, position="MC", role="b2b_support")], as_of=AS_OF)
        self.assertLess(form.multiplier("28106293", "vertical_442", "MC", "b2b_support"), 1.0)
        self.assertEqual(form.multiplier("28106293", "vertical_442", "MC", "cm_support"), 1.0)  # other role
        self.assertEqual(form.multiplier("28106293", "balanced_442", "MC", "b2b_support"), 1.0)  # other tactic
        self.assertEqual(form.multiplier("28106293", "vertical_442", "DM", "b2b_support"), 1.0)  # other position
        self.assertEqual(form.multiplier("31039582", "vertical_442", "MC", "b2b_support"), 1.0)  # other player

    def test_the_last_ten_count_and_newer_ones_count_more(self) -> None:
        form = build_form([appearance(3 * age, 7.0) for age in range(12)], as_of=AS_OF)
        (job,) = form.jobs.values()
        self.assertEqual(len(job.ratings), 10)
        self.assertEqual(job.ratings[0].date, AS_OF)
        self.assertAlmostEqual(job.ratings[0].weight, 1.0)
        self.assertAlmostEqual(job.ratings[9].weight, 0.87 ** 9)  # about 30% of the latest
        # A recent poor game outweighs an equally poor older one.
        recent_bad = build_form([appearance(0, 5.0), appearance(30, 8.0)], as_of=AS_OF)
        old_bad = build_form([appearance(0, 8.0), appearance(30, 5.0)], as_of=AS_OF)
        key = ("28106293", "vertical_442", "ST", "af_attack")
        self.assertLess(recent_bad.jobs[key].average, old_bad.jobs[key].average)

    def test_a_part_match_counts_by_its_share_and_a_cameo_not_at_all(self) -> None:
        form = build_form([appearance(3, 7.0, minutes=45), appearance(10, 7.0, minutes=20)], as_of=AS_OF)
        (job,) = form.jobs.values()
        self.assertEqual(len(job.ratings), 1)
        self.assertAlmostEqual(job.ratings[0].weight, 0.5)

    def test_only_the_window_up_to_the_date_counts(self) -> None:
        form = build_form([appearance(91, 5.0), appearance(-1, 5.0)], as_of=AS_OF)
        self.assertEqual(form.jobs, {})

    def test_an_appearance_whose_job_is_not_known_is_left_out(self) -> None:
        self.assertEqual(build_form([appearance(3, 5.0, usable=False)], as_of=AS_OF).jobs, {})

    def test_the_change_is_at_most_two_percent_either_way(self) -> None:
        for rating, bound in ((10.0, 1.02), (1.0, 0.98)):
            form = build_form([appearance(3 * age, rating) for age in range(10)], as_of=AS_OF)
            multiplier = form.multiplier("28106293", "vertical_442", "ST", "af_attack")
            self.assertLessEqual(abs(multiplier - 1), abs(bound - 1))
            self.assertNotEqual(multiplier, 1.0)


if __name__ == "__main__":
    unittest.main()

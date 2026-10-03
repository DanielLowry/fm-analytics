"""Evidence thresholds and role-specific scouting discovery."""
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE, ScoutingCandidate, ScoutingFilters, assess_scouting_candidates
from fm_analytics.analytics.scouting import matches_information_filters
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.web.rendering import _scouting_filters
from tests.web_support import FIXTURE, WebServerHelpers, write_complete_fixture


def discovery_players():
    role = MVP_CATALOGUE.roles['af_attack']
    exact = AttributeObservation(Visibility.KNOWN, value=16)
    ranged = AttributeObservation(Visibility.RANGE, minimum=12, maximum=18)
    base = ScoutingCandidate(
        id='partial', name='Partial Target', positions=('ST',),
        attributes={role.attributes[0].name: exact, role.attributes[1].name: ranged},
        attributes_observed_at='2019-07-21', has_scout_report=True,
    )
    return (
        base,
        replace(base, id='lower', name='Lower Target', attributes={
            role.attributes[0].name: AttributeObservation(Visibility.KNOWN, value=3),
            role.attributes[1].name: AttributeObservation(Visibility.RANGE, minimum=2, maximum=4),
        }),
        replace(base, id='full', name='Fully Known', attributes={a.name: exact for a in role.attributes}),
        replace(base, id='blank', name='Blank Target', attributes={}),
        replace(base, id='unrelated', name='Unrelated Evidence', attributes={'corners': exact}),
        replace(base, id='uncaptured', name='Uncaptured Target', attributes={}, attributes_observed_at=None),
        replace(base, id='defender', name='Wrong Position', positions=('DC',)),
    )


class DiscoveryFilterTests(unittest.TestCase):
    def test_evidence_threshold_counts_exact_and_ranges_with_inclusive_boundary(self):
        for minimum, expected in ((None, True), (0, True), (3, True), (4, False)):
            with self.subTest(minimum=minimum):
                self.assertEqual(matches_information_filters(
                    ScoutingFilters(minimum_known_attributes=minimum), captured=True,
                    known=1, ranged=2, unknown=5, floor=10, ceiling=90,
                ), expected)

    def test_more_to_learn_needs_evidence_and_unresolved_attributes(self):
        for known, ranged, unknown, captured, expected in (
            (1, 0, 2, True, True), (0, 3, 0, True, True),
            (3, 0, 0, True, False), (0, 0, 3, True, False),
            (1, 1, 1, False, False),
        ):
            with self.subTest(known=known, ranged=ranged, unknown=unknown, captured=captured):
                self.assertEqual(matches_information_filters(
                    ScoutingFilters(scout_more_only=True), captured=captured,
                    known=known, ranged=ranged, unknown=unknown, floor=10, ceiling=90,
                ), expected)

    def test_counts_only_the_selected_roles_attributes(self):
        players = assess_scouting_candidates(discovery_players(), MVP_CATALOGUE, ScoutingFilters(
            role_key='af_attack', position='ST', minimum_known_attributes=2, scout_more_only=True,
        ))
        self.assertEqual({p.candidate.id for p in players}, {'partial', 'lower'})

    def test_query_defaults_to_median_but_respects_explicit_sort(self):
        for context, expected in (({}, 'median'), ({'role': ['af_attack']}, 'median'),
                                  ({'tactic': ['balanced_442']}, 'player_median')):
            query = context | {'scoutMore': ['1'], 'minKnown': ['2']}
            filters = _scouting_filters(query)
            self.assertEqual(filters.ranking_sort, expected)
            self.assertEqual(filters.minimum_known_attributes, 2)
            self.assertTrue(filters.scout_more_only)
            self.assertEqual(_scouting_filters(query | {'sort': ['age']}).ranking_sort, 'age')
            self.assertEqual(_scouting_filters(query | {'sort': ['unavailable']}).ranking_sort, expected)

    def test_invalid_counts_are_rejected(self):
        for value in ('-1', '1.5', 'abc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _scouting_filters({'minKnown': [value]})
        for value in (-1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ScoutingFilters(minimum_known_attributes=value)


class DiscoveryPageTests(WebServerHelpers, unittest.TestCase):
    def test_discovery_is_role_specific_and_sorted_by_median(self):
        port = self._serve(FIXTURE, discovery_players)
        query = '?position=ST&role=af_attack&scoutMore=1&minKnown=2'
        for route in ('/scouting', '/scouting/results'):
            status, body = self._get(port, route + query)
            self.assertEqual(status, 200)
            self.assertEqual(re.findall(r"<tr data-player-id='([^']+)'>", body), ['partial', 'lower'])
            self.assertIn('Sorted by <b>Median (best guess)</b>', body)
        status, body = self._get(port, '/scouting' + query)
        self.assertIn('<legend>Who to scout more</legend>', body)
        self.assertIn("name='minKnown' type='number' min='0' step='1' value='2'", body)
        self.assertIn("name='scoutMore' type='checkbox' value='1' checked", body)
        self.assertIn('scoutMore=1', body)

    def test_threshold_is_inclusive_and_can_exclude_everyone(self):
        port = self._serve(FIXTURE, discovery_players)
        for minimum, expected in ((0, ['partial', 'lower']), (2, ['partial', 'lower']), (3, [])):
            status, body = self._get(port, f'/scouting/results?role=af_attack&scoutMore=1&minKnown={minimum}')
            self.assertEqual(status, 200)
            self.assertEqual(re.findall(r"<tr data-player-id='([^']+)'>", body), expected)

    def test_tactic_discovery_uses_its_sortable_median_scenario(self):
        with tempfile.TemporaryDirectory() as directory:
            port = self._serve(write_complete_fixture(Path(directory)), discovery_players)
            status, body = self._get(port,
                '/scouting?tactic=balanced_442&position=ST&role=af_attack&scoutMore=1&minKnown=2')
        self.assertEqual(status, 200)
        self.assertEqual(re.findall(r"<tr data-player-id='([^']+)'>", body), ['partial', 'lower'])
        self.assertIn('Sorted by <b>Median scenario (player fit)</b>', body)
        self.assertIn("value='player_median'", body)


if __name__ == '__main__':
    unittest.main()

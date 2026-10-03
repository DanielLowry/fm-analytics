"""Full, uncertainty-preserving spreadsheet exports and their scouting context."""
import base64
import csv
import io
import json
import re
import shutil
import subprocess
import unittest
from dataclasses import replace

from fm_analytics.analytics import ScoutingCandidate, CandidateHistory, HistoricalReading
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.web.attribute_export import candidate_export_record, export_schema
from tests.web_support import FIXTURE, ROOT, WebServerHelpers


def export_player():
    return ScoutingCandidate(
        id='outfield', name='Visible Player', age=19, club='Example FC', positions=('ST',),
        attributes={
            'finishing': AttributeObservation(Visibility.KNOWN, value=15),
            'pace': AttributeObservation(Visibility.RANGE, minimum=9, maximum=15),
            'leadership': AttributeObservation(Visibility.KNOWN, value=12),
        }, attributes_observed_at='2019-07-21', raw_position_familiarity={'ST': 20, 'GK': 0},
    )


class AttributeExportTests(unittest.TestCase):
    def test_full_schemas_include_non_role_attributes_and_distinct_keeper_columns(self):
        schema = export_schema()['attributes']
        outfield = {key for key, label in schema['outfield']}
        goalkeeper = {key for key, label in schema['goalkeeper']}
        self.assertEqual(len(outfield), 36)
        self.assertEqual(len(goalkeeper), 38)
        self.assertLessEqual({'freeKickTaking', 'penaltyTaking', 'longThrows', 'leadership'}, outfield)
        self.assertLessEqual({'handling', 'eccentricity', 'tendencyToPunch', 'reflexes', 'passing'}, goalkeeper)
        self.assertFalse(outfield & {'handling', 'eccentricity', 'tendencyToPunch', 'reflexes'})
        self.assertFalse(goalkeeper & {'corners', 'crossing', 'marking', 'tackling'})

    def test_raw_positions_and_familiarity_need_the_existing_list_opt_in(self):
        player = replace(export_player(), positions=(), raw_positions=('ST',))
        record = candidate_export_record(player)
        self.assertEqual(record['familiarity'], {})
        self.assertEqual(record['positions'], [])
        opted_in = candidate_export_record(player, include_raw_positions=True)
        self.assertEqual(opted_in['positions'], ['ST'])
        self.assertEqual(opted_in['familiarity'], {'ST': 20, 'GK': 0})
        self.assertIn('Raw', opted_in['familiaritySource'])

    def test_missing_positions_remain_explicitly_ambiguous(self):
        blank = replace(export_player(), positions=(), attributes={})
        self.assertEqual(candidate_export_record(blank)['families'], ['outfield', 'goalkeeper'])
        keeper = replace(blank, positions=('GK',))
        self.assertEqual(candidate_export_record(keeper)['families'], ['goalkeeper'])

    def test_current_and_remembered_values_retain_their_provenance(self):
        player = replace(export_player(), history=CandidateHistory(
            as_of='2019-07-21', in_current_feed=True, out_of_date_before='2019-07-01',
            attributes={'pace': HistoricalReading('2019-06-01', '2019-06-30', 'current')},
        ), last_known_attributes={'finishing': AttributeObservation(Visibility.KNOWN, value=20)})
        record = candidate_export_record(player)
        self.assertEqual(record['attributes']['finishing'], '15')
        self.assertEqual(record['attributes']['pace'], '9-15')
        self.assertEqual(record['historical'], {'pace': '2019-06-30'})

    @unittest.skipUnless(shutil.which('node'), 'Node is required for spreadsheet encoding')
    def test_spreadsheet_encoding_preserves_ranges_quotes_missing_values_and_zero_familiarity(self):
        source = (ROOT / 'frontend/scripts/attribute-export-data.js').read_bytes()
        module = 'data:text/javascript;base64,' + base64.b64encode(source).decode()
        script = f"""
        import {{ attributeExport }} from '{module}';
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        process.stdout.write(JSON.stringify(['tsv', 'csv'].map(format =>
          attributeExport(input.rows, input.schema, 'outfield', format))));
        """
        record = candidate_export_record(replace(export_player(), name='=Formula', club='FC "Quoted", Town'), include_raw_positions=True)
        record['historical'] = {'pace': '2019-06-30'}
        keeper = candidate_export_record(replace(export_player(), positions=('GK',)))
        result = subprocess.run(['node', '--input-type=module', '-e', script],
            input=json.dumps({'rows': [record, keeper], 'schema': export_schema()}),
            capture_output=True, text=True, check=True)
        for fmt, encoded in zip(('tsv', 'csv'), json.loads(result.stdout)):
            with self.subTest(fmt=fmt):
                self.assertEqual(encoded['count'], 1)
                if fmt == 'csv':
                    headers, values = list(csv.reader(io.StringIO(encoded['text'])))
                else:
                    headers, values = [line.split('\t') for line in encoded['text'].splitlines()]
                row = dict(zip(headers, values))
                self.assertEqual(len(headers), len(values))
                self.assertEqual(row['Name'], "'=Formula")
                self.assertEqual(row['Club'], 'FC "Quoted", Town')
                self.assertEqual(row['Pace'], "'9-15")
                self.assertEqual(row['Finishing'], '15')
                self.assertEqual(row['Leadership'], '12')
                self.assertEqual(row['Corners'], '?')
                self.assertEqual(row['Familiarity GK (0–20)'], '0')
                self.assertEqual(row['Familiarity ST (0–20)'], '20')
                self.assertEqual(row['Familiarity DC (0–20)'], '?')
                self.assertIn('Pace: last seen 2019-06-30', row['Historical attributes'])


class AttributeExportPageTests(WebServerHelpers, unittest.TestCase):
    def test_exports_are_available_on_scouting_and_both_player_report_types(self):
        port = self._serve(FIXTURE, lambda: (export_player(),))
        squad_player_id = load_fixture(FIXTURE)[1].players[0].id
        for path in ('/scouting', '/scouting/player/outfield', '/squad/player/' + squad_player_id):
            status, body = self._get(port, path)
            self.assertEqual(status, 200)
            self.assertIn('Copy outfield attributes', body)
            self.assertIn('Copy goalkeeper attributes', body)
            self.assertIn("data-export-format='csv'", body)
            payload = json.loads(re.search(r"data-export-schema>(.*?)</script>", body, re.S).group(1))
            self.assertEqual(payload['schema'], json.loads(json.dumps(export_schema())))
            if path != '/scouting':
                self.assertEqual(len(payload['rows']), 1)
                self.assertIsNotNone(payload['rows'][0]['age'])

    def test_snapshot_exports_the_full_pool_and_respects_raw_position_context(self):
        players = tuple(replace(export_player(), id=f'player-{index}', name=f'Player {index}') for index in range(125))
        port = self._serve(FIXTURE, lambda: players)
        for raw in ('', '&includeRawPositions=1'):
            status, body = self._get(port, '/scouting/results?snapshot=1&role=af_attack&name=missing' + raw)
            self.assertEqual(status, 200)
            payload = json.loads(re.search(r"id='scouting-snapshot'>(.*?)</script>", body, re.S).group(1))
            self.assertEqual(len(payload['rows']), 125)
            self.assertEqual(payload['rows'][0]['export']['familiarity'], {'GK': 0, 'ST': 20} if raw else {})
            self.assertEqual(payload['rows'][0]['export']['attributes']['pace'], '9-15')

        if shutil.which('node'):
            def module(name):
                return 'data:text/javascript;base64,' + base64.b64encode((ROOT / 'frontend/scripts' / name).read_bytes()).decode()
            script = f"""
            import {{ orderedSnapshotRows }} from '{module('scouting-data.js')}';
            import {{ attributeExport }} from '{module('attribute-export-data.js')}';
            import {{ readFileSync }} from 'node:fs';
            const input = JSON.parse(readFileSync(0, 'utf8'));
            const answer = ['', 'Player 12'].map(name => {{
              const params = new URLSearchParams({{sort: 'name', dir: 'asc', limit: '100', name}});
              const rows = orderedSnapshotRows(input.snapshot, params).map(row => row.export);
              return attributeExport(rows, input.schema, 'outfield');
            }});
            process.stdout.write(JSON.stringify(answer));
            """
            output = subprocess.run(['node', '--input-type=module', '-e', script],
                input=json.dumps({'snapshot': payload, 'schema': export_schema()}),
                capture_output=True, text=True, check=True)
            all_players, filtered = json.loads(output.stdout)
            self.assertEqual(all_players['count'], 125)
            self.assertEqual(filtered['count'], 6)
            self.assertEqual([line.split('\t')[0] for line in filtered['text'].splitlines()[1:]],
                             ['Player 12', 'Player 120', 'Player 121', 'Player 122', 'Player 123', 'Player 124'])


if __name__ == '__main__':
    unittest.main()

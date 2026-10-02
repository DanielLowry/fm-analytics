"""Regression coverage for snapshots, filter parity, and progressive reports."""
import base64
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import urlencode

from fm_analytics.web.scouting_pages import _safe_scouting_return
from fm_analytics.web.ui import ordered_positions
from tests.test_web_scouting_states import ALL_STATE_PLAYERS
from tests.web_support import FIXTURE, ROOT, WebServerHelpers


class TableConventionTests(unittest.TestCase):
    def test_pitch_order_is_back_to_front_and_left_to_right(self):
        self.assertEqual(
            ordered_positions(['ST', 'AMR', 'DC', 'MC', 'GK', 'DL', 'DR', 'AML', 'MR', 'ML', 'DMC']),
            ('GK', 'DL', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MR', 'AML', 'AMR', 'ST'),
        )
        self.assertEqual(ordered_positions(['custom', 'ST', 'GK']), ('GK', 'ST', 'custom'))

    def test_return_navigation_accepts_only_the_scouting_list(self):
        self.assertEqual(_safe_scouting_return('/scouting?view=all&name=Alex&limit=200'), '/scouting?view=all&name=Alex&limit=200')
        for unsafe in ['https://evil.example/scouting', '//evil.example/scouting', '/squad', '/scouting/player/id', '/scouting\nX: bad', '/scouting\\evil', 'https://[bad']:
            with self.subTest(unsafe=unsafe):
                self.assertEqual(_safe_scouting_return(unsafe), '/scouting?view=scouted')


class ScoutingSnapshotTests(WebServerHelpers, unittest.TestCase):
    def snapshot(self, port, context):
        status, body = self._get(port, '/scouting/results?' + urlencode(context | {'snapshot': '1'}))
        self.assertEqual(status, 200)
        source = re.search(r"<script type='application/json' id='scouting-snapshot'>(.*?)</script>", body, re.S)
        self.assertIsNotNone(source)
        return json.loads(source.group(1))

    @unittest.skipUnless(shutil.which('node'), 'Node is required to verify browser filter parity')
    def test_browser_filters_match_server_in_both_list_modes(self):
        port = self._serve(FIXTURE, lambda: ALL_STATE_PLAYERS)
        source = (ROOT / 'frontend/scripts/scouting-data.js').read_bytes()
        module = 'data:text/javascript;base64,' + base64.b64encode(source).decode()
        script = f"""
        import {{ orderedSnapshotRows }} from '{module}';
        import {{ readFileSync }} from 'node:fs';
        const input = JSON.parse(readFileSync(0, 'utf8'));
        const answer = input.queries.map(query => {{
          const params = new URLSearchParams(query);
          return orderedSnapshotRows(input.snapshot, params).map(row => row.id);
        }});
        process.stdout.write(JSON.stringify(answer));
        """
        filters = [
            {}, {'name': 'current'}, {'name': 'nonexistent'}, {'everScouted': '1'},
            {'view': 'scouted'}, {'view': 'scouted', 'everScouted': '1'},
            {'minAge': '21'}, {'maxAge': '21'}, {'maxValue': '100000'},
            {'visibility': 'known'}, {'visibility': 'partial'}, {'visibility': 'unknown'},
            {'minFloor': '40'}, {'minCeiling': '90'},
            {'minCeiling': '90', 'includeUnlikely': '1'},
            {'market': 'gettable'}, {'market': 'free'}, {'market': 'listed'}, {'market': 'expiring', 'expiringMonths': '0'},
            {'transferInterest': 'interested'}, {'transferInterest': 'not_interested'},
            {'loanInterest': 'interested'}, {'loanInterest': 'not_interested'},
            {'club': 'old', 'everScouted': '1'}, {'fact.example': 'nonexistent'},
        ]
        for context in ({}, {'role': 'af_attack', 'position': 'ST'}):
            snapshot = self.snapshot(port, context | {'name': 'nonexistent'})
            self.assertEqual({row['id'] for row in snapshot['rows']}, {player.id for player in ALL_STATE_PLAYERS})
            queries = [context | query | {'sort': 'median', 'dir': 'desc'} for query in filters]
            queries += [context | {'sort': sort, 'dir': direction, 'everScouted': '1'}
                        for sort in snapshot['orders']
                        for direction in ('asc', 'desc')]
            if context:
                queries += [context | {'sort': 'priority', 'dir': direction, 'everScouted': '1', 'minCeiling': '90', 'includeUnlikely': '1'} for direction in ('asc', 'desc')]
            completed = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps({'snapshot': snapshot, 'queries': queries}), capture_output=True, text=True, check=True)
            browser = json.loads(completed.stdout)
            for query, actual in zip(queries, browser):
                with self.subTest(context=context, query=query):
                    status, body = self._get(port, '/scouting/results?' + urlencode(query))
                    self.assertEqual(status, 200)
                    expected = re.findall(r"<tr data-player-id='([^']+)'>", body)
                    self.assertEqual(actual, expected)

    def test_snapshot_escapes_candidate_content_in_script_and_rows(self):
        from dataclasses import replace
        player = replace(ALL_STATE_PLAYERS[0], name='</script><script>alert(1)</script>', id='quoted\'id')
        port = self._serve(FIXTURE, lambda: (player,))
        snapshot = self.snapshot(port, {})
        self.assertEqual(snapshot['rows'][0]['name'], player.name.casefold())
        self.assertNotIn('<script>', snapshot['rows'][0]['html'])
        self.assertIn('&lt;script&gt;', snapshot['rows'][0]['html'])
        self.assertIn('quoted&#x27;id', snapshot['rows'][0]['html'])

    def test_report_return_context_and_sections_are_preserved(self):
        port = self._serve(FIXTURE, lambda: ALL_STATE_PLAYERS)
        back = '/scouting?view=all&name=current&sort=age&limit=200'
        status, body = self._get(port, '/scouting/player/state-exact?' + urlencode({'return': back}))
        self.assertEqual(status, 200)
        self.assertIn("href='/scouting?view=all&amp;name=current&amp;sort=age&amp;limit=200'", body)
        self.assertIn("id='player-attributes'><summary>", body)
        self.assertIn("class='position-role-report fm-disclosure'><summary>", body)
        self.assertNotIn("class='position-role-report fm-disclosure' open", body)
        self.assertLess(body.index("href='#player-roles'"), body.index("id='player-roles'"))

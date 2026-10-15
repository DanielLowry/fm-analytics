"""Complete shipped settings, faithful benchmarks and original-file delivery."""

import io
import json
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.catalogue import load_catalogue
from fm_analytics.analytics.in_possession import in_possession_selected_instructions
from fm_analytics.analytics.in_transition import in_transition_selected_instructions
from fm_analytics.analytics.out_of_possession import out_of_possession_selected_instructions
from fm_analytics.analytics.tactical_system import effective_instructions
from fm_analytics.web.out_of_possession_render import out_of_possession_section
from fm_analytics.web.tactic_download import send_tactic_download
from fm_analytics.web.tactic_setup_render import tactic_setup_section
from tests.test_in_possession import ROLE, TACTIC


class InstructionAuditTests(unittest.TestCase):
    def test_every_shipped_tactic_has_a_complete_explicit_setup(self):
        for tactic in MVP_CATALOGUE.tactics.values():
            with self.subTest(tactic=tactic.key):
                self.assertFalse(tactic.in_possession_missing_fields)
                self.assertFalse(tactic.in_transition_missing_fields)
                self.assertFalse(tactic.out_of_possession_missing_fields)
                self.assertTrue(tactic.setup_notes)
                selected = set(tactic.instructions + in_possession_selected_instructions(tactic.in_possession)
                               + in_transition_selected_instructions(tactic.in_transition)
                               + out_of_possession_selected_instructions(tactic.out_of_possession))
                self.assertEqual(set(tactic.instruction_rationale), selected)

    def test_published_roles_are_pinned_and_match_source_screenshots(self):
        apache = MVP_CATALOGUE.tactics['apache_v1']
        rosler = MVP_CATALOGUE.tactics['rosler_lls_442']
        self.assertEqual(apache.mentality, 'Attacking')
        self.assertEqual(apache.in_possession.attacking_width, 'Extremely Wide')
        self.assertEqual(apache.out_of_possession.defensive_line, 'Standard')
        self.assertEqual({s.key: s.role_key for s in apache.slots if s.position in ('AMC', 'MC', 'DM')},
                         {'AMCR': 'ss_attack', 'MCL': 'cm_attack', 'DM': 'dlp_dm_support'})
        self.assertEqual(rosler.in_transition.distribution_types, ())
        self.assertEqual(rosler.out_of_possession.tackling, 'Get Stuck In')
        self.assertEqual([s.role_key for s in rosler.slots if s.position == 'DC'], ['cd_defend'] * 2)
        self.assertEqual([s.role_key for s in rosler.slots if s.position == 'ST'], ['pf_attack'] * 2)
        self.assertEqual([s.role_key for s in rosler.slots if s.position == 'MC'], ['cm_support'] * 2)
        for tactic in (apache, rosler):
            self.assertTrue(tactic.source)
            self.assertTrue(tactic.out_of_possession.use_offside_trap)
            self.assertTrue(all(not s.alternate_role_keys for s in tactic.slots))
            self.assertIn('not fully decoded', tactic.source.verification)

    def test_new_unmodelled_defensive_controls_do_not_change_instruction_scores(self):
        tactic = replace(MVP_CATALOGUE.tactics['vertical_442'], instruction_rationale={})
        for width in ('Narrow', 'Standard', 'Wide'):
            changed = replace(tactic, out_of_possession=replace(
                tactic.out_of_possession, defensive_width=width, use_offside_trap=True, tackling='Get Stuck In',
            ))
            self.assertEqual(effective_instructions(changed), effective_instructions(tactic))
            displayed = out_of_possession_selected_instructions(changed.out_of_possession)
            self.assertIn('Use Offside Trap', displayed)
            self.assertIn('Get Stuck In', displayed)
            self.assertIn(f'Defensive width</span><b>{width}</b>', out_of_possession_section(changed))

    def test_setup_does_not_claim_the_catalogue_contains_all_published_player_instructions(self):
        for key in ('apache_v1', 'rosler_lls_442'):
            section = tactic_setup_section(MVP_CATALOGUE.tactics[key])
            self.assertIn(f"href='/tactics/{key}/download'", section)
            self.assertIn('See original FM file', section)
            self.assertIn('not fully decoded', section)
        section = tactic_setup_section(MVP_CATALOGUE.tactics['rosler_lls_442'])
        self.assertIn('<td>DL</td><td>Sit Narrower</td>', section)


class OriginalTacticDownloadTests(unittest.TestCase):
    def handler(self):
        handler = Mock()
        handler.wfile = io.BytesIO()
        return handler

    def test_original_files_download_without_a_squad_or_game_connection(self):
        for key, length in (('apache_v1', 46931), ('rosler_lls_442', 47153)):
            tactic = MVP_CATALOGUE.tactics[key]
            handler = self.handler()
            send_tactic_download(handler, f'/tactics/{key}/download', {})
            handler.send_response.assert_called_once_with(200)
            content = handler.wfile.getvalue()
            self.assertEqual(len(content), length)
            self.assertEqual(sha256(content).hexdigest(), tactic.source.sha256)
            self.assertIn(b'afe.', content[:16])
            handler.send_header.assert_any_call(
                'Content-Disposition', f'attachment; filename="{tactic.source.filename}"',
            )

    def test_unknown_and_traversal_paths_cannot_download_other_files(self):
        for key in ('balanced_442', 'missing', '../catalogue.json', '%2E%2E%2Fcatalogue.json', 'apache_v1/extra'):
            handler = self.handler()
            send_tactic_download(handler, f'/tactics/{key}/download', {})
            handler.send_error.assert_called_once()
            self.assertEqual(handler.send_error.call_args.args[0], 404)
            self.assertEqual(handler.wfile.getvalue(), b'')

    def test_corrupt_and_missing_originals_fail_without_serving_bytes(self):
        for error in (None, FileNotFoundError()):
            handler = self.handler()
            with patch('fm_analytics.web.tactic_download.resources.files') as files:
                reader = files.return_value.joinpath.return_value.read_bytes
                reader.return_value = b'corrupted'
                reader.side_effect = error
                send_tactic_download(handler, '/tactics/apache_v1/download', {})
            self.assertEqual(handler.send_error.call_args.args[0], 503)
            self.assertEqual(handler.wfile.getvalue(), b'')


class SetupSchemaTests(unittest.TestCase):
    def load(self, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalogue.json'
            path.write_text(json.dumps({'version': 'v', 'roles': [ROLE], 'tactics': [{**TACTIC, **overrides}]}))
            return load_catalogue(path).tactics['shape']

    def test_slot_instructions_load_and_bad_values_fail(self):
        self.assertEqual(self.load(slots=[{**s, 'instructions': ['Sit Narrower']} for s in TACTIC['slots']]).slots[0].instructions,
                         ('Sit Narrower',))
        for value in (['Sit Narrower', 'Sit Narrower'], [True], '', [None]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load(slots=[{**s, 'instructions': value} for s in TACTIC['slots']])

    def test_source_rejects_unsafe_filenames_urls_hashes_and_ignored_keys(self):
        original = MVP_CATALOGUE.tactics['apache_v1'].source
        for change in ({'filename': '../apache.fmf'}, {'filename': 'attack\r\nheader.fmf'},
                       {'url': 'http://example.org/tactic'}, {'sha256': 'unverified'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(original, **change)
        with self.assertRaises(ValueError):
            self.load(source={'typo': 'author'})


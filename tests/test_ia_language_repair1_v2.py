"""Repair-1 v2: terra-high profile data, the Experimental AI preview label, and the bounded live-UI questions
(Q2 county + 2024 map wording, Q3 source referent copy, Q4 bare district number with a held plan).
Fake transport/secret/ledger only: no network, model, Count or credential."""
import copy
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
import uuid
from public_app import load_core
from districtbrief.geography import geometry_payload
from districtbrief.interpret import recipe
from districtbrief.investigation import Investigation
from districtbrief.ia_language import (EMPTY_PLAN, FUNCTION_NAME, SCHEMA_VERSION, LanguageError, convert_decision,
                                       prepare_request, wire_plan)
from districtbrief.ia_language_funding import reservation
from districtbrief.ia_language_profiles import PROFILES_PATH, load_profile, load_profiles
from districtbrief.ia_language_provider import PROMPT, OpenAIProvider, configuration_hash, provider_payload
from language_funding_fixture import PROFILE, SOL, bound, funding_record, ledger_fixture, usage
import test_ia_language_contract as contract_fixtures

ROOT = Path(__file__).resolve().parents[1]
HIGH = load_profile('terra-high')
def D(chamber, code): return {'state_fips': '15', 'chamber': chamber, 'code': code, 'boundary_session': 2024}
def high_funding(**over):
    profiles = load_profiles()
    f = dict(admission={'test': {'terra-medium': 150, 'terra-high': 30}, 'demo': {'terra-medium': 100}},
             profile_hashes={k: profiles[k].profile_hash for k in ('terra-medium', 'terra-high')}, max_starts=280)
    f.update(over)
    return funding_record(**f)

class TerraHighProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.i = Investigation(load_core())
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        h = contract_fixtures.LanguageContractTests(); h.i = self.i; self.prepared = prepare_request(h.request(), self.i, 'session')
        self.calls = []
        decision = {'status': 'uncertain', 'intent': 'none', 'plan': copy.deepcopy(EMPTY_PLAN), 'focus_alias': '', 'clarify_field': '',
                    'clarify_choices': [], 'reason_code': 'uncertain_interpretation', 'inherited_fields': []}
        self.decision = decision
        self.body = {'status': 'completed', 'model': 'gpt-6.1-terra', 'service_tier': 'default', 'reasoning': {'effort': 'high'},
                     'usage': usage(1000, 1800, reasoning=1500),
                     'output': [{'type': 'function_call', 'name': FUNCTION_NAME, 'status': 'completed', 'arguments': json.dumps(decision)}]}
    def transport(self, method, path, body, secret, deadline):
        self.calls.append((path, copy.deepcopy(body)))
        if path.endswith('input_tokens'): return 200, {'object': 'response.input_tokens', 'input_tokens': 1000}
        return 200, copy.deepcopy(self.body)
    def interpret(self, ledger, events=None, bucket='test'):
        return OpenAIProvider(transport=self.transport, secret_reader=lambda: 'fake-secret-never-network').interpret(
            self.prepared, ledger, bucket, threading.Event(), time.monotonic() + 25, lambda: None,
            **({'diagnostic_sink': events.append} if events is not None else {}))

    def test_terra_high_is_data_with_medium_caps_rates_and_exact_expected_identity(self):
        self.assertEqual(sorted(load_profiles()), ['sol-low', 'terra-high', 'terra-medium'])
        self.assertEqual((HIGH.model, HIGH.reasoning_effort, HIGH.service_tier, HIGH.max_input_tokens, HIGH.max_output_tokens),
                         ('gpt-6.1-terra', 'high', 'default', 12288, 2048))
        self.assertEqual((HIGH.expected_model, HIGH.expected_service_tier, HIGH.expected_reasoning_effort), ('gpt-6.1-terra', 'default', 'high'))
        self.assertEqual(HIGH.rates, PROFILE.rates)
        self.assertEqual(reservation(HIGH), reservation(PROFILE))
        # Adding the data leaves every existing profile identity unchanged (no silent re-pricing or renaming).
        self.assertEqual(PROFILE.profile_hash, 'sha256:da428920bbeb97e362a5fe961d2e7c54e87b977fcabd312b490babd8c1b86385')
        self.assertEqual(SOL.profile_hash, 'sha256:e87b9a4f3229d39ec4d5f08a76700403bc19b4af44c6f26dab1f4aa7a9e3a612')
        self.assertNotEqual(HIGH.profile_hash, PROFILE.profile_hash)
        d = json.loads(PROFILES_PATH.read_text())['profiles']
        self.assertEqual({k: v for k, v in d['terra-high'].items() if k not in ('reasoning_effort', 'expected_response')},
                         {k: v for k, v in d['terra-medium'].items() if k not in ('reasoning_effort', 'expected_response')})

    def test_high_payload_and_count_differ_from_medium_only_in_reasoning_effort(self):
        hi, hi_count, hi_stats = provider_payload(self.prepared, HIGH); med, med_count, med_stats = provider_payload(self.prepared, PROFILE)
        self.assertEqual((hi['model'], hi['reasoning'], hi_count['reasoning']), ('gpt-6.1-terra', {'effort': 'high'}, {'effort': 'high'}))
        for a, b in ((hi, med), (hi_count, med_count)):
            self.assertEqual({k: v for k, v in a.items() if k != 'reasoning'}, {k: v for k, v in b.items() if k != 'reasoning'})
        self.assertEqual((hi['instructions'], hi['tools'], hi['max_output_tokens'], hi['service_tier']), (PROMPT, med['tools'], 2048, 'default'))
        self.assertEqual(hi_stats['prompt_sha256'], med_stats['prompt_sha256'])
        self.assertNotEqual(configuration_hash('sha256:' + 'c' * 64, HIGH), configuration_hash('sha256:' + 'c' * 64, PROFILE))

    def test_explicitly_admitted_high_sends_high_verifies_identity_and_settles_at_terra_rates(self):
        ledger = ledger_fixture(self.tmp.name, profile=HIGH, funding=high_funding()); events = []
        decision, meta = self.interpret(ledger, events)
        self.assertEqual(decision, self.decision)
        self.assertEqual([p for p, _ in self.calls], ['/v1/responses/input_tokens', '/v1/responses'])
        self.assertTrue(all(b['model'] == 'gpt-6.1-terra' and b['reasoning'] == {'effort': 'high'} for _, b in self.calls))
        self.assertEqual(events[0]['identity'], {'model': 'gpt-6.1-terra', 'service_tier': 'default', 'effort': 'high', 'profile_id': 'terra-high',
            'expected_model': 'gpt-6.1-terra', 'expected_service_tier': 'default', 'expected_effort': 'high', 'verified': True})
        s = ledger.summary()
        self.assertEqual(s['buckets']['test']['new_settled_nano_usd'], 1000 * 1000 + 1800 * 5000)
        self.assertEqual(s['admission']['test']['terra-high'], {'cap': 30, 'used': 1, 'remaining': 29})
        self.assertEqual(s['admission']['test']['terra-medium']['used'], 0)
        self.assertNotIn('terra-high', s['admission']['demo'])  # no public/demo High admission
        entry = json.loads(ledger.path.read_text())['entries'][0]
        self.assertEqual((entry['profile_id'], entry['profile_hash']), ('terra-high', HIGH.profile_hash))

    def test_medium_response_to_high_request_is_an_identity_mismatch_not_a_fallback(self):
        ledger = ledger_fixture(self.tmp.name, profile=HIGH, funding=high_funding()); self.body['reasoning'] = {'effort': 'medium'}
        with self.assertRaises(LanguageError) as failure: self.interpret(ledger)
        self.assertEqual(failure.exception.code, 'provider_identity_mismatch')
        self.assertTrue(ledger.summary()['unresolved'])

    def test_high_needs_explicit_funding_pin_and_admission_before_any_network(self):
        # Existing funding (Medium/Sol only): High is unapproved. A pin without any bucket admission is an invalid record.
        # Admitted for test only: a demo (public) start is not admitted.
        with self.assertRaises(LanguageError) as bad:
            ledger_fixture(self.tmp.name, funding=high_funding(admission={'test': {'terra-medium': 150}, 'demo': {'terra-medium': 100}}))
        self.assertEqual(bad.exception.code, 'approval_unavailable')
        for code, funding, bucket in (('approval_unavailable', funding_record(), 'test'), ('profile_not_admitted', high_funding(), 'demo')):
            with self.subTest(code=code):
                tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
                medium = ledger_fixture(tmp.name, funding=funding); ledger = bound(medium, HIGH); self.calls.clear()
                with self.assertRaises(LanguageError) as failure: self.interpret(ledger, bucket=bucket)
                self.assertEqual(failure.exception.code, code); self.assertEqual(self.calls, [])

    def test_operator_env_selects_high_and_no_client_or_ui_switch_exists(self):
        import os
        from unittest.mock import patch
        import public_app
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with patch.dict(os.environ, {'HAIC_LANGUAGE_ENABLED': '1', 'HAIC_LANGUAGE_PROFILE': 'terra-high'}), \
                patch('districtbrief.ia_language_provider.read_secret', side_effect=AssertionError('secret')):
            a = public_app.Application(tmp.name, secure_cookie=False)
        self.addCleanup(lambda: [h.close() for h in a.service.metrics.handlers])
        out = []; health = json.loads(b''.join(a({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/api/health'}, lambda s, h: out.append(s))))
        self.assertEqual({k: health['language_profile'][k] for k in HIGH.public_identity()}, HIGH.public_identity())
        for f in (ROOT / 'static').iterdir():
            self.assertNotRegex(f.read_text(encoding='utf-8'), r'terra-high|terra-medium|reasoning_effort|HAIC_LANGUAGE_PROFILE', f.name)

class PreviewLabelTests(unittest.TestCase):
    def test_label_is_inside_ask_section_hidden_by_default_and_follows_language_enabled(self):
        html = (ROOT / 'static/index.html').read_text(encoding='utf-8'); js = (ROOT / 'static/investigation.js').read_text(encoding='utf-8')
        section = html[html.index('<section id="ia-question"'):html.index('</section>', html.index('<section id="ia-question"'))]
        self.assertIn('<span id="ia-question-preview" class="preview-label" hidden>Experimental AI preview</span>', section)
        self.assertIn("$('#ia-question-preview').hidden = !enabled;", js)
        off = re.search(r'<p id="ia-language-off"[^>]*>(.*?)</p>', html).group(1)
        self.assertNotIn('preview', off.lower())
        label = re.search(r'class="preview-label" hidden>(.*?)<', html).group(1)
        self.assertFalse(re.search(r'sha256|[0-9a-f]{12}|gpt-|%|score', label))
        # Review-before-Apply barriers are unchanged.
        for text in ('Use this proposal in the draft', 'Discard proposal', 'No question is sent automatically.'):self.assertIn(text, js)

class LiveQuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.i = Investigation(load_core())
    held = recipe(D('house', '028'))
    def request(self, text, confirmed):
        return {'schema_version': SCHEMA_VERSION, 'request_id': str(uuid.uuid4()), 'utterance': text, 'context': {
            'case_id': str(uuid.uuid4()), 'branch_id': str(uuid.uuid4()), 'revision': 1, 'snapshot_id': self.i.snapshot_id,
            'operation_version': 'ia-core/1', 'recipe_version': confirmed['issue_id'] + '/1', 'confirmed_plan': copy.deepcopy(confirmed),
            'draft_plan': copy.deepcopy(confirmed), 'focused_step_id': None, 'selected_claim_refs': []}}
    def run_(self, text, proposal, wire_map=0, held=None):
        p = prepare_request(self.request(text, held or self.held), self.i, 's')
        d = {'status': 'propose', 'intent': 'replace_plan', 'plan': dict(wire_plan(proposal), map_session=wire_map), 'focus_alias': '',
             'clarify_field': '', 'clarify_choices': [], 'reason_code': '', 'inherited_fields': []}
        return convert_decision(p, d, self.i.core)
    def refused(self, code, *a, **kw):
        with self.assertRaises(LanguageError) as c: self.run_(*a, **kw)
        self.assertEqual(c.exception.code, code)
    def county(self):
        p = copy.deepcopy(self.held); p['steps'].append({'step_id': 's5', 'operation': 'compare', 'args': {'metric_ids': ['poverty_rate_65_plus'], 'comparison_geography': 'HI-COUNTY-003-2024'}})
        return p

    def test_q2_honolulu_county_and_2024_boundary_on_the_map(self):
        # Data first: Honolulu County has the measure, Core runs the canonical plan on the 2024 map, and the House 028
        # 2024-session boundary geometry is bundled.
        p24 = dict(self.county(), map_session=2024)
        run = self.i.handle({'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1', 'recipe_version': 'aging_at_home/1',
            'snapshot_id': self.i.snapshot_id, 'request_id': str(uuid.uuid4()), 'case_id': str(uuid.uuid4()), 'branch_id': str(uuid.uuid4()),
            'revision': 0, 'mode': 'run', 'plan': p24, 'selected_claim_refs': [], 'selected_action_ref': None})
        self.assertEqual((run['status'], [s['status'] for s in run['steps']]), ('ok', ['ok'] * 5))
        self.assertTrue(geometry_payload(self.i.core.packet, self.i.snapshot_id, 'house', '028', 2024))
        u = 'For this same House 028 older-adult investigation, compare senior poverty with Honolulu County and show the 2024 boundary on the map.'
        out = self.run_(u, self.county(), 2024)
        self.assertEqual((out['status'], out['normalized_plan']['map_session']), ('propose', 2024))
        self.assertEqual(sorted(x['field'] for x in out['typed_diff']), ['map_session', 'steps'])
        self.refused('explicit_map_unreported', u, self.county(), 0)  # never silently keep the 2026 map
        for text in ('Compare senior poverty with Honolulu County on the 2024 boundary map.',
                     'Compare senior poverty with Honolulu County and switch the map to the 2024 session.',
                     'Compare senior poverty with Honolulu County; show the 2024 session boundaries on the map.'):
            with self.subTest(text=text):self.assertEqual(self.run_(text, self.county(), 2024)['normalized_plan']['map_session'], 2024)
        # Unchanged protections: statistical/data-period wording is not a map year; negation excludes it.
        for text in ('Compare senior poverty with Honolulu County using the 2024 boundaries.',
                     'Compare senior poverty with Honolulu County for the 2020-2024 period.'):
            with self.subTest(text=text):self.refused('explicit_map_unstated_change', text, self.county(), 2024)
        self.refused('explicit_map_conflict', 'Compare senior poverty with Honolulu County, not on the 2024 boundary map.', self.county(), 2024)

    def test_q3_source_inspection_does_not_change_question_context_and_referent_copy_is_plain(self):
        state_js = (ROOT / 'static/language_state.js').read_text(encoding='utf-8')
        # repair-1 v4: one shared builder; an inspected current finding and an explicit step focus are ephemeral scope.
        self.assertIn('focused_step_id:focused, selected_claim_refs:refs', state_js)
        js = (ROOT / 'static/investigation.js').read_text(encoding='utf-8')
        self.assertIn("if (result.clarify_field === 'referent')", js)
        self.assertIn("choice.field === 'referent' && sourceLabels[choice.label] ? srcLabel(choice.label)", js)
        # Server: with no selected claim a referential source question still clarifies (never a guessed source or prose).
        p = prepare_request(self.request('Explain the source I just selected for senior poverty in House 028.', self.held), self.i, 's')
        self.assertEqual(p['provider_context']['selected'], {})
        d = {'status': 'propose', 'intent': 'inspect_source', 'plan': copy.deepcopy(EMPTY_PLAN), 'focus_alias': 'source_3', 'clarify_field': '',
             'clarify_choices': [], 'reason_code': '', 'inherited_fields': []}
        with self.assertRaises(LanguageError) as c: convert_decision(p, d, self.i.core)
        self.assertEqual(c.exception.code, 'ambiguous_reference')

    def test_q4_bare_district_number_never_borrows_the_held_chamber(self):
        h13 = dict(copy.deepcopy(self.held), district=D('house', '013')); s13 = dict(copy.deepcopy(self.held), district=D('senate', '013'))
        for p in (h13, s13):
            out = self.run_('Switch to district 13 and show senior poverty.', p)
            self.assertEqual((out['status'], out['clarify_field'], [c['alias'] for c in out['choices']], out['recovered_from']),
                             ('clarify', 'district', ['d_h013', 'd_s013'], 'explicit_district_missing'))
        # Only the House has 26-51; a stated chamber decides; explicit forms are unchanged.
        h40 = dict(copy.deepcopy(self.held), district=D('house', '040'))
        self.assertEqual(self.run_('Switch to district 40.', h40)['normalized_plan']['district'], D('house', '040'))
        self.assertEqual(self.run_('Switch to senate district 13 and show senior poverty.', s13)['normalized_plan']['district'], D('senate', '013'))
        self.assertEqual(self.run_('Switch to House 13 and show senior poverty.', h13)['normalized_plan']['district'], D('house', '013'))
        self.refused('explicit_district_conflict', 'Switch to senate district 13.', h13)
        # Bare comparator number (Q13 policy): the held primary stays and the chamber is asked as a comparator choice.
        cmp20 = copy.deepcopy(self.held); cmp20['steps'][1]['args']['comparison_geography'] = 'HI-HOUSE-020-2024'
        out = self.run_('Stack it up against district 20.', cmp20)
        self.assertEqual((out['clarify_field'], [c['alias'] for c in out['choices']]), ('comparator', ['g_HI-HOUSE-020-2024', 'g_HI-SENATE-020-2024']))
        self.assertIn('never borrow the held chamber', PROMPT)

if __name__ == '__main__': unittest.main()

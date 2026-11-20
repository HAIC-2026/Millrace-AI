"""Ask keeps the original 20-measure domain while guided controls admit added ACS measures.

Offline only: an injected transport records any provider access, the ledger is a temporary fixture and no
request leaves the process. A guided-only plan, focus or selection is refused before Core work, provider
payload, rate-limit slot, ledger reservation or quota use."""
import copy
import io
import json
import tempfile
import unittest
import uuid
from unittest.mock import patch
from public_app import Application, load_core
from districtbrief.claim_binding import digest
from districtbrief.core import ORIGINAL_METRIC_IDS
from districtbrief.investigation import Investigation
from districtbrief.ia_language import (EMPTY_PLAN, GUIDED_ONLY_CODE, GUIDED_ONLY_MESSAGE, SCHEMA_VERSION,
    LanguageError, guided_only_metric_ids, prepare_request, value_free_catalog, wire_plan)
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import OpenAIProvider
from language_funding_fixture import ledger_fixture, usage

ORIGINAL_CATALOG_DIGEST = 'sha256:cc6467496100f8aff2f54096b4f4daf798f296fe6e1e75403200d66df4cb00eb'
ADDED = 'households_with_snap'


class GuidedOnlyAskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.i = Investigation(load_core())
        cls.core = cls.i.core

    def plan(self, steps, chamber='house', code='028'):
        return {'district': {'state_fips': '15', 'chamber': chamber, 'code': code, 'boundary_session': 2024},
                'map_session': 2026, 'issue_id': 'custom', 'service_area_id': None, 'steps': steps}

    def compare(self, metric, step='s1'):
        return {'step_id': step, 'operation': 'compare', 'args': {'metric_ids': [metric], 'comparison_geography': 'HI-STATE-2024'}}

    def request(self, confirmed=None, draft=None, focus=None, refs=(), utterance='Compare senior poverty with the State.'):
        held = confirmed or draft
        return {'schema_version': SCHEMA_VERSION, 'request_id': str(uuid.uuid4()), 'utterance': utterance, 'context': {
            **{k: str(uuid.uuid4()) for k in ('case_id', 'branch_id')}, 'revision': 1, 'snapshot_id': self.i.snapshot_id,
            'operation_version': 'ia-core/1', 'recipe_version': held['issue_id'] + '/1' if held else 'custom/1',
            'confirmed_plan': copy.deepcopy(confirmed), 'draft_plan': copy.deepcopy(draft), 'focused_step_id': focus,
            'selected_claim_refs': list(refs)}}

    def claim_ref(self, plan, finding_id):
        run = {'schema_version': 'haic-investigation/1', 'request_id': str(uuid.uuid4()),
               **{k: str(uuid.uuid4()) for k in ('case_id', 'branch_id')}, 'revision': 1, 'snapshot_id': self.i.snapshot_id,
               'operation_version': 'ia-core/1', 'recipe_version': 'custom/1', 'mode': 'run', 'plan': plan,
               'selected_claim_refs': [], 'selected_action_ref': None}
        return next(c['claim_ref'] for c in self.i.handle(run)['claims'] if c['claim_ref']['finding_id'] == finding_id)

    def guarded_requests(self):
        added = self.plan([self.compare(ADDED)])
        mixed = self.plan([self.compare('poverty_rate_65_plus'), {'step_id': 's2', 'operation': 'profile',
                                                                  'args': {'metric_ids': ['median_age', 'disability_share']}}])
        original = self.plan([self.compare('poverty_rate_65_plus')])
        guided = self.plan([self.compare('poverty_rate_65_plus'), self.compare(ADDED, 's2')])
        ref = self.claim_ref(guided, f'stat:HI-HOUSE-028-2024:{ADDED}')
        return {
            'explicit draft': self.request(draft=added),
            'confirmed and draft': self.request(confirmed=mixed, draft=mixed),
            'draft beside an original confirmed plan': self.request(confirmed=original, draft=added),
            'focused added step': self.request(confirmed=mixed, draft=mixed, focus='s2'),
            'selected added finding': self.request(confirmed=original, draft=original, refs=[ref]),
        }

    def test_ask_domain_is_the_original_ordered_20_with_the_original_digest(self):
        self.assertEqual(len(ORIGINAL_METRIC_IDS), 20)
        self.assertGreaterEqual(len(self.core.metrics), 32)
        self.assertEqual(self.core.original_metric_ids(), list(ORIGINAL_METRIC_IDS))
        catalog = value_free_catalog(self.core)
        self.assertEqual([m['metric_id'] for m in catalog['metrics']], list(ORIGINAL_METRIC_IDS))
        self.assertEqual(digest(catalog), ORIGINAL_CATALOG_DIGEST)
        added = [m for m in self.core.metrics.values() if m['guided_only']]
        self.assertEqual(len(added), len(self.core.metrics) - 20)
        self.assertTrue(all(m['group'] != 'Other' and m['label'] != m['published_label'] for m in added))
        p = prepare_request(self.request(draft=self.plan([self.compare('poverty_rate_65_plus')])), self.i, 'session')
        self.assertEqual(p['catalog_digest'], ORIGINAL_CATALOG_DIGEST)
        enum = p['schema']['properties']['plan']['properties']['steps']['items']['properties']['metric_ids']['items']['enum']
        self.assertEqual(enum, list(ORIGINAL_METRIC_IDS))
        self.assertFalse({a for a in p['choices'] if a.startswith('m_')} - {'m_' + m for m in ORIGINAL_METRIC_IDS})

    def test_null_plan_profile_keeps_the_original_20_while_lookup_shows_every_measure(self):
        run = {'schema_version': 'haic-investigation/1', 'request_id': str(uuid.uuid4()),
               **{k: str(uuid.uuid4()) for k in ('case_id', 'branch_id')}, 'revision': 1, 'snapshot_id': self.i.snapshot_id,
               'operation_version': 'ia-core/1', 'recipe_version': 'custom/1', 'mode': 'run',
               'plan': self.plan([{'step_id': 's1', 'operation': 'profile', 'args': {'metric_ids': None}}]),
               'selected_claim_refs': [], 'selected_action_ref': None}
        out = self.i.handle(run)
        self.assertEqual([c['claim_ref']['finding_id'].rsplit(':', 1)[1] for c in out['claims']], list(ORIGINAL_METRIC_IDS))
        self.assertEqual(len(self.core.profile('HI-HOUSE-028-2024')['findings']), len(self.core.metrics))
        # A held null profile is the original domain, not a guided-only use.
        self.assertEqual(guided_only_metric_ids((run['plan'],), [], self.core), [])
        prepare_request(self.request(confirmed=run['plan'], draft=run['plan']), self.i, 'session')

    def test_guided_only_scope_is_refused_before_core_payload_quota_and_ledger(self):
        for name, request in self.guarded_requests().items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                ledger = ledger_fixture(tmp); before = ledger.summary(); calls = []; secrets = []
                def transport(*args): calls.append(args); raise AssertionError('provider access')
                def secret(): secrets.append(1); return 'fake-no-network'
                service = LanguageService(self.i, enabled=True, ledger=ledger,
                                          provider=OpenAIProvider(transport=transport, secret_reader=secret))
                try:
                    with patch.object(self.i, 'handle', side_effect=AssertionError('Core run')), \
                         patch.object(ledger, 'acquire_job', side_effect=AssertionError('ledger slot')):
                        code, out = service.handle('start', copy.deepcopy(request), 'session-a')
                    self.assertEqual((code, out['status'], out['code'], out['model_calls']), (409, 'error', GUIDED_ONLY_CODE, 0))
                    self.assertEqual(out['attribution']['failure_class'], 'start_refused')
                    self.assertEqual((calls, secrets, list(service._site), service._active, dict(service._jobs)), ([], [], [], None, {}))
                    self.assertEqual(ledger.summary(), before)
                    # The question, plan and selections the client sent are not rewritten or stripped.
                    with self.assertRaises(LanguageError) as c:prepare_request(copy.deepcopy(request), self.i, 'session')
                    self.assertEqual((c.exception.code, c.exception.status), (GUIDED_ONLY_CODE, 409))
                finally:
                    service.close()

    def test_original_scope_still_starts_and_settles_once(self):
        original = self.plan([self.compare('poverty_rate_65_plus')])
        request = self.request(confirmed=original, draft=original)
        arguments = json.dumps({'status': 'propose', 'intent': 'replace_plan', 'plan': wire_plan(original), 'focus_alias': '',
                                'clarify_field': '', 'clarify_choices': [], 'reason_code': '', 'inherited_fields': []})
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ledger_fixture(tmp); calls = []
            def transport(method, path, body, secret, deadline):
                calls.append(path)
                if path.endswith('input_tokens'):return 200, {'object': 'response.input_tokens', 'input_tokens': 8000}
                return 200, {'model': 'gpt-6.1-terra', 'service_tier': 'default', 'reasoning': {'effort': 'medium'}, 'status': 'completed',
                             'usage': usage(8000, 100), 'output': [{'type': 'function_call', 'name': 'ia_language_decision',
                                                                    'status': 'completed', 'arguments': arguments}]}
            service = LanguageService(self.i, enabled=True, ledger=ledger,
                                      provider=OpenAIProvider(transport=transport, secret_reader=lambda: 'fake-no-network'))
            try:
                code, out = service.handle('start', request, 'session-a')
                self.assertEqual((code, out['status'], out['model_calls']), (202, 'pending', 0))
                service._executor.shutdown(wait=True)
                code, out = service.handle('status', {'schema_version': SCHEMA_VERSION, 'request_id': request['request_id']}, 'session-a')
                self.assertEqual((code, out['status'], out['model_calls']), (200, 'propose', 1))
                self.assertEqual(len(calls), 2)
                self.assertEqual(ledger.summary()['count_requests'], 1)
            finally:
                service.close()

    def test_http_start_delivers_the_typed_message_before_funding(self):
        guarded = self.guarded_requests()['explicit draft']
        # Language is enabled with no funding record, budget or secret: an admissible start would fail at funding,
        # while the guided-only start is answered first with its typed message and no model call.
        with tempfile.TemporaryDirectory() as state, patch.dict('os.environ', {'HAIC_LANGUAGE_ENABLED': '1', 'HAIC_LANGUAGE_PROFILE': 'terra-medium'}):
            app = Application(state, secure_cookie=False)
            self.addCleanup(app.language.close)
            for handler in app.service.metrics.handlers:
                self.addCleanup(handler.close)
            with patch.object(app.language, '_resources', side_effect=AssertionError('funding or provider access')):
                def http(path, payload=None, cookie=''):
                    raw = b'' if payload is None else json.dumps(payload).encode()
                    env = {'REQUEST_METHOD': 'GET' if payload is None else 'POST', 'PATH_INFO': path, 'QUERY_STRING': '',
                           'wsgi.input': io.BytesIO(raw), 'HTTP_HOST': 'local.test', 'HTTP_COOKIE': cookie,
                           'CONTENT_LENGTH': str(len(raw)), 'CONTENT_TYPE': 'application/json'}
                    response = []
                    data = b''.join(app(env, lambda status, headers: response.extend((status, dict(headers)))))
                    return response[0], response[1], json.loads(data)
                status, headers, catalog = http('/api/catalog')
                cookie = headers['Set-Cookie'].split(';', 1)[0]
                self.assertEqual(len([m for m in catalog['metrics'] if m['guided_only']]), len(catalog['metrics']) - 20)
                status, headers, out = http('/api/language/start', guarded, cookie)
            self.assertEqual(status, '409 Conflict')
            self.assertEqual((out['code'], out['message'], out['model_calls']), (GUIDED_ONLY_CODE, GUIDED_ONLY_MESSAGE, 0))
            self.assertIn('Content-Security-Policy', headers)
            self.assertEqual(list(app.language._site), [])


if __name__ == '__main__':
    unittest.main()

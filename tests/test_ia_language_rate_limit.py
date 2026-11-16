"""Public language admission: 3 admitted question starts per rolling 300 s across the whole site, no per-session cap.
Injected fake transport/secret/ledger and a controllable monotonic offset: no network, model, Count or credential."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from public_app import load_core
from districtbrief import ia_language_jobs as jobs
from districtbrief.investigation import Investigation
from districtbrief.ia_language import EMPTY_PLAN, SCHEMA_VERSION
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import OpenAIProvider
from language_funding_fixture import ledger_fixture, usage
import test_ia_language_contract as contract_fixtures

ROOT = Path(__file__).resolve().parents[1]

class Clock:
    """time.monotonic for the jobs module only: real time plus a test-controlled offset (provider deadlines stay real)."""
    def __init__(self): self.offset = 0.0; self._real = time.monotonic
    def monotonic(self): return self._real() + self.offset
    def __getattr__(self, name): return getattr(time, name)

class SiteRateLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.i = Investigation(load_core())
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.ledger = ledger_fixture(self.tmp.name)
        self.transports = []; self.release = threading.Event(); self.release.set(); self.entered = threading.Event()
        decision = {'status': 'uncertain', 'intent': 'none', 'plan': copy.deepcopy(EMPTY_PLAN), 'focus_alias': '', 'clarify_field': '',
                    'clarify_choices': [], 'reason_code': 'uncertain_interpretation', 'inherited_fields': []}
        def transport(method, path, body, secret, deadline):
            self.transports.append(path)
            if path.endswith('input_tokens'): return 200, {'object': 'response.input_tokens', 'input_tokens': 1000}
            self.entered.set(); self.release.wait(3)
            return 200, {'model': 'gpt-6.1-terra', 'service_tier': 'default', 'reasoning': {'effort': 'medium'}, 'status': 'completed', 'usage': usage(),
                         'output': [{'type': 'function_call', 'name': 'ia_language_decision', 'status': 'completed', 'arguments': json.dumps(decision)}]}
        self.service = LanguageService(self.i, enabled=True, provider=OpenAIProvider(transport=transport, secret_reader=lambda: 'fake-no-network'), ledger=self.ledger)
        self.clock = Clock(); p = patch.object(jobs, 'time', self.clock); p.start(); self.addCleanup(p.stop)
    def tearDown(self):
        self.release.set(); self.service.close()
        if self.service._executor: self.service._executor.shutdown(wait=True)
        self.tmp.cleanup()
    def request(self):
        h = contract_fixtures.LanguageContractTests(); h.i = self.i; return h.request()
    def start(self, session):
        """One public start; an admitted job is driven to its terminal state so the next start is not 'busy'."""
        r = self.request(); code, out = self.service.handle('start', r, session)
        if code == 202:
            for _ in range(300):
                if self.service._active is None: break
                time.sleep(.01)
            self.assertIsNone(self.service._active)
        return code, out
    def demo_entries(self): return self.ledger.summary()['buckets']['demo']['entries']
    def denied(self, session):
        before = (len(self.transports), self.demo_entries(), list(self.service._site))
        code, out = self.start(session)
        self.assertEqual((code, out['code'], out['model_calls']), (429, 'shared_demonstration_rate_limit', 0))
        self.assertIn('3 language questions every 5 minutes across the site', out['message'])
        # Refused start: no Count, no generation, no ledger reservation, and nothing recorded in the window.
        self.assertEqual((len(self.transports), self.demo_entries(), list(self.service._site)), before)

    def test_bootstrap_reports_only_the_site_window(self):
        limits = self.service.bootstrap()['limits']
        self.assertEqual(limits, {'utterance_characters': 500, 'deadline_seconds': 25, 'site_starts_per_window': 3, 'site_window_seconds': 300})
        self.assertNotIn('session_starts_per_hour', json.dumps(self.service.bootstrap()))

    def test_third_admitted_fourth_blocked_across_any_sessions_until_oldest_ages_out(self):
        for session in ('a', 'b', 'c'):
            self.assertEqual(self.start(session)[0], 202)
        self.assertEqual((len(self.transports), self.demo_entries()), (6, 3))  # 3 admitted = 3 Count + 3 generation
        for session in ('a', 'd', 'e'):self.denied(session)
        self.clock.offset += 299.5; self.denied('f')  # still inside the rolling window of the first start
        self.clock.offset += 0.6; self.assertEqual(self.start('f')[0], 202)  # all three (same instant) aged out: recovery
        for session in ('g', 'a'):self.assertEqual(self.start(session)[0], 202)
        self.denied('h')  # the new window is full again, whichever session asks

    def test_exact_rolling_boundary_and_denials_never_extend_the_window(self):
        for session in 'abc':
            self.assertEqual(self.start(session)[0], 202); self.clock.offset += 100
        site = list(self.service._site); self.assertEqual(len(site), 3)  # recorded admission times, 100 s apart
        # Just inside the boundary (the start runs a few ms after this offset is set, so allow 200 ms margin).
        self.clock.offset = site[0] + 300 - time.monotonic() - 0.2; self.denied('d'); self.denied('d')
        self.clock.offset = site[0] + 300 - time.monotonic() + 0.001; self.assertEqual(self.start('d')[0], 202)  # at/after boundary
        self.assertEqual(len(self.service._site), 3); self.denied('e')
        self.clock.offset = site[1] + 300 - time.monotonic() + 0.001; self.assertEqual(self.start('e')[0], 202)

    def test_no_per_session_limit_one_session_can_use_the_whole_site_window_repeatedly(self):
        for _ in range(3):self.assertEqual(self.start('solo')[0], 202)
        self.denied('solo')
        self.clock.offset += 300.01
        for _ in range(3):self.assertEqual(self.start('solo')[0], 202)  # 6 starts in ~5 min: old 5/session/hour cap is gone
        self.denied('other')
        self.clock.offset += 300.01
        self.assertEqual(self.start('solo')[0], 202)
        self.assertEqual(self.demo_entries(), 7)

    def test_concurrent_public_starts_admit_one_and_record_only_admitted(self):
        self.release.clear(); results = []; barrier = threading.Barrier(8)
        reqs = [self.request() for _ in range(8)]
        def go(k):
            barrier.wait(); results.append(self.service.handle('start', reqs[k], f's{k}')[0])
        threads = [threading.Thread(target=go, args=(k,)) for k in range(8)]
        for th in threads:th.start()
        for th in threads:th.join(5)
        self.assertEqual(sorted(results), [202] + [409] * 7)  # existing one-at-a-time rule; busy refusals record nothing
        self.assertEqual(len(self.service._site), 1)
        self.release.set(); self.service._executor.shutdown(wait=True); self.service._executor = None
        self.assertEqual(self.demo_entries(), 1)

    def test_private_operator_starts_are_not_throttled_and_do_not_consume_the_public_window(self):
        for session in ('a', 'b', 'c'):self.assertEqual(self.start(session)[0], 202)
        self.denied('d')
        for _ in range(4):
            r = self.request(); self.assertEqual(self.service.operator_start(r)[0], 202); self.service.operator_wait(r['request_id'])
        self.assertEqual(len(self.service._site), 3)
        self.assertEqual(self.ledger.summary()['buckets']['test']['entries'], 4)
        self.denied('d')

    def test_status_of_a_finished_job_is_not_expired_by_the_shorter_window(self):
        r = self.request(); self.assertEqual(self.service.handle('start', r, 'a')[0], 202)
        for _ in range(300):
            if self.service._active is None: break
            time.sleep(.01)
        self.clock.offset += 400  # past the 300 s rate window, inside the existing 600 s job retention
        code, out = self.service.handle('status', {'schema_version': SCHEMA_VERSION, 'request_id': r['request_id']}, 'a')
        self.assertEqual((code, out['status']), (200, 'uncertain'))
        self.assertEqual(self.service.handle('status', {'schema_version': SCHEMA_VERSION, 'request_id': r['request_id']}, 'b')[0], 403)  # session binding kept

    def test_public_copy_states_the_new_limit_and_never_the_old_ones(self):
        for name in ('static/investigation.js', 'README.md', 'districtbrief/ia_language_jobs.py'):
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertNotRegex(text, r'5 (?:language )?questions per (?:browser )?session|15 (?:shared|per hour)|per session per hour')
        self.assertIn('3 language questions every 5 minutes across the site', (ROOT / 'static/investigation.js').read_text(encoding='utf-8'))
        self.assertIn('rolling 5-minute (300-second) window across the whole site', (ROOT / 'README.md').read_text(encoding='utf-8'))

if __name__ == '__main__': unittest.main()

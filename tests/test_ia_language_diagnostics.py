"""Private opt-in synthetic smoke diagnostics. HTTP and evaluate never opt in."""
import os
import copy
import importlib.util
import io
import json
from pathlib import Path
import stat
import threading
import time
import unittest
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import patch
import test_ia_language_proposals as proposal_fixtures
from districtbrief.ia_language import SCHEMA_VERSION

class LanguageDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.fixture=proposal_fixtures.LanguageProposalTests();self.fixture.setUp()
        self.f=self.fixture
    def tearDown(self):self.fixture.tearDown()
    def operator(self):
        path=Path(__file__).resolve().parents[1]/'tools/ia_language_operator.py'
        spec=importlib.util.spec_from_file_location('operator_diagnostic_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    def test_operator_events_distinguish_exact_local_rejection_from_model_uncertain(self):
        f=self.f;request=f.request('Profile median age in House28.');decision=f.decision(f.plan('custom'))
        decision['plan']['steps'][0]['program_ids']=['snap_hi'];f.decisions.append(decision);events=[]
        code,out=f.service.operator_start(request,diagnostic_sink=events.append);self.assertEqual(code,202)
        code,out=f.service.operator_wait(request['request_id']);self.assertEqual(out['status'],'uncertain')
        self.assertEqual([e['event']for e in events],['provider_result','local_result'])
        self.assertEqual(json.loads(events[0]['function_arguments']),decision);self.assertEqual(events[0]['settlement'],'known_usage_settled')
        local=events[1];self.assertEqual(local['phase'],'validation');self.assertEqual(local['rejection_code'],'inapplicable_provider_fields')
        self.assertEqual(local['exception_type'],'LanguageError');self.assertTrue(local['frames'])
        self.assertNotIn('function_arguments',out);self.assertNotIn('diagnostic_sink',f.service._jobs[request['request_id']])
        self.assertFalse(f.ledger.summary()['unresolved'])
    def test_unknown_local_exception_records_frames_without_exception_message(self):
        f=self.f;request=f.request('Profile median age in House28.');f.decisions.append(f.decision(f.plan('custom')));events=[]
        with patch('districtbrief.ia_language_jobs.convert_decision',side_effect=ValueError('PRIVATE_NOTE_CANARY Authorization: never-copy')):
            self.assertEqual(f.service.operator_start(request,diagnostic_sink=events.append)[0],202)
            code,out=f.service.operator_wait(request['request_id'])
        self.assertEqual(out['status'],'error');self.assertEqual(events[1]['exception_type'],'ValueError')
        self.assertNotIn('PRIVATE_NOTE_CANARY',json.dumps(events));self.assertNotIn('Authorization',json.dumps(events))
        self.assertFalse(f.ledger.summary()['unresolved']);self.assertEqual(f.ledger.summary()['buckets']['test']['settled_usage_estimate_nano_usd'],1500000)
    def test_diagnostic_io_failures_do_not_change_operator_result_or_settlement(self):
        f=self.f;request=f.request('Profile median age in House28.');f.decisions.append(f.decision(f.plan('custom')))
        def failed(event):raise OSError('injected file full')
        self.assertEqual(f.service.operator_start(request,diagnostic_sink=failed)[0],202)
        code,out=f.service.operator_wait(request['request_id']);self.assertEqual(out['status'],'propose')
        self.assertFalse(f.ledger.summary()['unresolved']);self.assertEqual(f.ledger.summary()['buckets']['test']['settled_usage_estimate_nano_usd'],1500000)
    def test_http_never_receives_operator_sink_or_emits_diagnostics(self):
        f=self.f;request=f.request('Profile median age in House28.');f.decisions.append(f.decision(f.plan('custom')))
        with patch('districtbrief.ia_language_jobs.emit_operator_diagnostic',side_effect=AssertionError('HTTP diagnostic')),patch('districtbrief.ia_language_provider._provider_diagnostic',side_effect=AssertionError('HTTP raw capture')):
            out=f.finish_http(request)
        self.assertEqual(out['status'],'propose');self.assertNotIn('function_arguments',json.dumps(out))
        spoof=f.request('Profile House28.');spoof['diagnostics']='/run/ia1-eval/results/stolen.jsonl'
        self.assertEqual(f.http('/api/language/start',spoof)[0],400)
        self.assertEqual(f.secret_reads,1)
    @patch.dict(os.environ,{'HAIC_LANGUAGE_OPERATOR_CUTOFF_EPOCH':str(int(time.time())+86400)})  # evaluator-supplied future cutoff
    def test_actual_cli_diagnostics_are_opt_in_0600_and_results_only(self):
        f=self.f;operator=self.operator();results=f.root/'results';results.mkdir(mode=0o700)
        question=f.root/'synthetic.jsonl';request=f.request('Profile median age in House28.')
        question.write_text(json.dumps({'case_id':'synthetic-only','request':request})+'\n');question.chmod(0o600)
        output=results/'out.jsonl';diagnostics=results/'diagnostics.jsonl';f.decisions.append(f.decision(f.plan('custom')))
        captured=io.StringIO()
        with patch.object(operator,'EVAL_ROOT',f.root),patch.object(operator,'load_core',return_value=f.i.core),patch.object(operator,'FundingLedger',return_value=f.ledger),patch('districtbrief.ia_language_jobs.OpenAIProvider',return_value=f.provider),redirect_stdout(captured):
            code=operator.main(['smoke','--profile','terra-medium','--questions',str(question),'--output',str(output),'--diagnostics',str(diagnostics)])
        self.assertEqual(code,0);summary=json.loads(captured.getvalue());self.assertTrue(summary['diagnostics']['enabled']);self.assertEqual(summary['diagnostics']['write_failures'],0)
        self.assertEqual(stat.S_IMODE(diagnostics.stat().st_mode),0o600)
        events=[json.loads(line)for line in diagnostics.read_text().splitlines()];self.assertEqual(len(events),2)
        self.assertEqual(events[0]['case_id'],'synthetic-only');self.assertEqual(events[1]['phase'],'validation');self.assertIsNone(events[1]['rejection_code'])
        self.assertEqual(f.ledger.summary()['buckets']['test']['settled_usage_estimate_nano_usd'],1500000)
    @patch.dict(os.environ,{'HAIC_LANGUAGE_OPERATOR_CUTOFF_EPOCH':str(int(time.time())+86400)})  # evaluator-supplied future cutoff
    def test_actual_cli_diagnostic_write_failure_reports_failure_after_settlement(self):
        f=self.f;operator=self.operator();results=f.root/'results';results.mkdir(mode=0o700)
        question=f.root/'synthetic.jsonl'
        question.write_text(''.join(json.dumps({'case_id':'synthetic-%d'%k,'request':f.request('Profile median age in House28.')})+'\n' for k in range(2)));question.chmod(0o600)
        f.decisions.append(f.decision(f.plan('custom')));f.decisions.append(f.decision(f.plan('custom')));real_fdopen=operator.os.fdopen;opened=[]
        class FailedWriter:
            def __init__(self,file):self.file=file
            def write(self,data):raise OSError('injected diagnostic file full')
            def flush(self):self.file.flush()
            def fileno(self):return self.file.fileno()
            def close(self):self.file.close()
        def fdopen(fd,*args,**kwargs):
            file=real_fdopen(fd,*args,**kwargs);opened.append(fd)
            return FailedWriter(file)if len(opened)==1 else file
        captured=io.StringIO()
        with patch.object(operator,'EVAL_ROOT',f.root),patch.object(operator,'load_core',return_value=f.i.core),patch.object(operator,'FundingLedger',return_value=f.ledger),patch('districtbrief.ia_language_jobs.OpenAIProvider',return_value=f.provider),patch.object(operator.os,'fdopen',side_effect=fdopen),redirect_stdout(captured):
            code=operator.main(['smoke','--profile','terra-medium','--questions',str(question),'--output',str(results/'out.jsonl'),'--diagnostics',str(results/'diagnostics.jsonl')])
        # Fail closed: the row in flight still settles its known usage, but no later row starts and the run reports failure.
        self.assertEqual(code,2);summary=json.loads(captured.getvalue());self.assertEqual(summary['status'],'diagnostics_failed')
        self.assertGreaterEqual(summary['diagnostics']['write_failures'],2)
        rows=[json.loads(x) for x in (results/'out.jsonl').read_text().splitlines()]
        self.assertEqual([r['status'] for r in rows],['propose','not_started']);self.assertEqual(rows[1]['response']['code'],'diagnostics_write_failed')
        self.assertEqual((rows[0]['ledger_delta']['count_requests'],rows[1]['ledger_delta']['count_requests'],rows[1]['model_calls']),(1,0,0))
        self.assertFalse(f.ledger.summary()['unresolved']);self.assertEqual(f.ledger.summary()['buckets']['test']['settled_usage_estimate_nano_usd'],1500000)
        self.assertEqual(f.ledger.summary()['new_starts'],1)
    @patch.dict(os.environ,{'HAIC_LANGUAGE_OPERATOR_CUTOFF_EPOCH':str(int(time.time())+86400)})
    def test_evaluate_diagnostics_capture_actual_identity_usage_and_raw_decision_per_case(self):
        f=self.f;operator=self.operator();results=f.root/'results';results.mkdir(mode=0o700)
        question=f.root/'synthetic.jsonl'
        question.write_text(''.join(json.dumps({'case_id':'synthetic-%03d'%k,'request':f.request('Profile median age in House28.')})+'\n' for k in range(120)))
        question.chmod(0o600)
        for _ in range(120):f.decisions.append(f.decision(f.plan('custom')))
        captured=io.StringIO()
        with patch.object(operator,'EVAL_ROOT',f.root),patch.object(operator,'load_core',return_value=f.i.core),patch.object(operator,'FundingLedger',return_value=f.ledger),patch('districtbrief.ia_language_jobs.OpenAIProvider',return_value=f.provider),redirect_stdout(captured):
            code=operator.main(['evaluate','--profile','terra-medium','--questions',str(question),'--output',str(results/'out.jsonl'),'--diagnostics',str(results/'out.diagnostics.jsonl')])
        self.assertEqual(code,0);summary=json.loads(captured.getvalue());self.assertEqual((summary['records'],summary['diagnostics']['write_failures']),(120,0))
        rows=[json.loads(x) for x in (results/'out.jsonl').read_text().splitlines()]
        events=[json.loads(x) for x in (results/'out.diagnostics.jsonl').read_text().splitlines()]
        self.assertEqual(stat.S_IMODE((results/'out.diagnostics.jsonl').stat().st_mode),0o600)
        by={}
        for e in events:by.setdefault(e['case_id'],[]).append(e)
        self.assertEqual(sorted(by),[r['case_id'] for r in rows])
        for r in rows:
            self.assertEqual((r['diagnostic_events'],r['model_calls'],r['ledger_delta']['count_requests'],r['ledger_delta']['generation_calls']),(2,1,1,1))
            pr,lr=by[r['case_id']]
            self.assertEqual((pr['event'],lr['event']),('provider_result','local_result'))
            self.assertEqual(pr['identity'],{'model':'gpt-6.1-terra','service_tier':'default','effort':'medium','profile_id':'terra-medium',
                'expected_model':'gpt-6.1-terra','expected_service_tier':'default','expected_effort':'medium','verified':True})
            self.assertEqual(pr['usage']['input_tokens'],r['ledger_delta']['usage']['input_tokens'])
            self.assertEqual(json.loads(pr['function_arguments'])['status'],'propose');self.assertEqual(pr['settlement'],'known_usage_settled')
            self.assertEqual((lr['phase'],lr['status'],lr['rejection_code']),('validation',r['status'],None))
        encoded=(results/'out.diagnostics.jsonl').read_bytes()
        for private in (b'injected-no-network',b'Authorization',b'Bearer',b'Profile median age'):self.assertNotIn(private,encoded)
    def test_diagnostics_outside_results_refused(self):
        f=self.f;operator=self.operator();results=f.root/'results';results.mkdir(mode=0o700)
        question=f.root/'synthetic.jsonl';question.write_text(json.dumps({'case_id':'synthetic-only','request':f.request('Profile House28.')})+'\n');question.chmod(0o600)
        with patch.object(operator,'EVAL_ROOT',f.root),patch.object(operator,'load_core',return_value=f.i.core),patch.object(operator,'FundingLedger',return_value=f.ledger),redirect_stdout(io.StringIO()):
            code=operator.main(['smoke','--profile','terra-medium','--questions',str(question),'--output',str(results/'out.jsonl'),'--diagnostics',str(f.root/'outside.jsonl')])
        self.assertEqual(code,2);self.assertEqual(f.secret_reads,0);self.assertEqual(f.paths,[])

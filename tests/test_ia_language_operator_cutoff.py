"""Operator/evaluator recovery cutoff: smoke/evaluate refuse to start, and record every not-yet-started row as
not started with 0 calls before any reservation, once the evaluator-supplied UTC epoch is reached. Absent or
malformed means refuse. Public HTTP serving has no such cutoff. Fake provider I/O only."""
import importlib.util
import io
import json
import os
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import test_ia_language_proposals as proposal_fixtures

ENV='HAIC_LANGUAGE_OPERATOR_CUTOFF_EPOCH'

class OperatorCutoffTests(unittest.TestCase):
    def setUp(self):
        self.f=proposal_fixtures.LanguageProposalTests();self.f.setUp()
        path=Path(__file__).resolve().parents[1]/'tools/ia_language_operator.py'
        spec=importlib.util.spec_from_file_location('operator_cutoff_test',path);self.op=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.op)
        self.results=self.f.root/'results';self.results.mkdir(mode=0o700)
    def tearDown(self):self.f.tearDown()
    def questions(self,n):
        q=self.f.root/'q.jsonl';rows=[]
        for k in range(n):
            rows.append(json.dumps({'case_id':f'synthetic-{k}','request':self.f.request('Profile median age in House28.')}))
            self.f.decisions.append(self.f.decision(self.f.plan('custom')))
        q.write_text('\n'.join(rows)+'\n');q.chmod(0o600);return q
    def run_cli(self,command,n,env,now=None,ledger=None):
        q=self.questions(n);out=io.StringIO();ledger=ledger or self.f.ledger
        patches=[patch.object(self.op,'EVAL_ROOT',self.f.root),patch.object(self.op,'load_core',return_value=self.f.i.core),
                 patch.object(self.op,'FundingLedger',return_value=ledger),patch('districtbrief.ia_language_jobs.OpenAIProvider',return_value=self.f.provider),
                 patch.dict(os.environ,env,clear=False)]
        if now is not None:patches.append(patch.object(self.op,'_now',now))
        for p in patches:p.start()
        try:
            if ENV not in env:os.environ.pop(ENV,None)
            with redirect_stdout(out):code=self.op.main([command,'--profile','terra-medium','--questions',str(q),'--output',str(self.results/(command+'.jsonl'))])
        finally:
            for p in reversed(patches):p.stop()
        return code,json.loads(out.getvalue())

    def untouched(self):
        s=self.f.ledger.summary()
        self.assertEqual((s['count_requests'],s['sequence'],s['buckets']['test']['entries']),(0,0,0));self.assertEqual(self.f.paths,[]);self.assertEqual(self.f.secret_reads,0)

    def test_absent_or_malformed_cutoff_refuses_before_ledger_and_input(self):
        for env in ({},{ENV:''},{ENV:'tomorrow'},{ENV:'1794753807.5'},{ENV:'-1'},{ENV:'0'}):
            for command in ('smoke','evaluate'):
                with self.subTest(env=env,command=command):
                    class Untouchable:
                        def __getattr__(s,name):raise AssertionError('ledger touched: '+name)
                    code,out=self.run_cli(command,1,env,ledger=Untouchable())
                    self.assertEqual((code,out['status'],out['code']),(2,'error','recovery_cutoff_unset'))
                    self.assertFalse((self.results/(command+'.jsonl')).exists())
        self.untouched()

    def test_shared_slot_busy_waits_without_losing_or_double_starting_rows(self):
        # The public app (another ledger object/process) holds the one-job slot; the study row waits, then runs once.
        from language_funding_fixture import bound,SOL
        other=bound(self.f.ledger,SOL);held=[other.acquire_job()];waits=[]
        def sleep(seconds):
            waits.append(seconds)
            if held:other.release_job(held.pop())
        with patch.object(self.op,'_sleep',sleep):
            code,out=self.run_cli('smoke',1,{ENV:str(int(time.time())+3600)})
        self.assertEqual(code,0);self.assertGreaterEqual(len(waits),1);self.assertEqual(held,[])
        rows=[json.loads(x) for x in (self.results/'smoke.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),1);self.assertNotEqual(rows[0]['status'],'busy');self.assertEqual(rows[0]['profile_id'],'terra-medium')
        s=self.f.ledger.summary();self.assertEqual((s['new_starts'],s['admission']['test']['terra-medium']['used']),(1,1))
    def capped(self,terra,sol):
        import tempfile
        from language_funding_fixture import funding_record,ledger_fixture
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        return ledger_fixture(tmp.name,funding=funding_record(admission={'test':{'terra-medium':terra,'sol-low':sol},'demo':{'terra-medium':1}},max_starts=terra+sol+1))
    def test_evaluate_needs_120_admitted_test_starts_for_its_own_profile_before_any_input(self):
        env={ENV:str(int(time.time())+3600)}
        for terra,sol in ((119,120),(119,0)):
            with self.subTest(terra=terra,sol=sol):
                ledger=self.capped(terra,sol);opened=[]
                with patch.object(self.op,'questions',side_effect=lambda *a,**k:opened.append(a)),patch.object(self.op,'protected_path',side_effect=lambda *a,**k:opened.append(a)):
                    code,out=self.run_cli('evaluate',120,env,ledger=ledger)
                self.assertEqual((code,out['code']),(2,'count_capacity_insufficient'))
                self.assertEqual((opened,self.f.paths,self.f.secret_reads),([],[],0))
                self.assertEqual(ledger.summary()['new_starts'],0)
        ledger=self.capped(120,0)
        code,out=self.run_cli('evaluate',120,env,ledger=ledger)
        self.assertEqual((code,out['status'],out['records']),(0,'completed',120))
        s=ledger.summary();self.assertEqual((s['admission']['test']['terra-medium'],s['buckets']['demo']['new_starts']),({'cap':120,'used':120,'remaining':0},0))
        self.assertEqual(self.f.secret_reads,120)
    def test_passed_cutoff_refuses_to_start(self):
        code,out=self.run_cli('smoke',2,{ENV:'1794753807'},now=lambda:1794753807.0)
        self.assertEqual((code,out['code']),(2,'recovery_cutoff_passed'));self.assertFalse((self.results/'smoke.jsonl').exists())
        self.untouched()

    def test_rows_not_started_after_cutoff_are_recorded_with_zero_calls_before_reserve(self):
        cutoff=1794753807;clock=iter([cutoff-60,cutoff-59]+[cutoff+1]*20)  # start check, row 1, then past
        code,out=self.run_cli('smoke',3,{ENV:str(cutoff)},now=lambda:next(clock))
        self.assertEqual(code,0);self.assertEqual(out['records'],3)
        rows=[json.loads(x) for x in (self.results/'smoke.jsonl').read_text().splitlines()]
        self.assertEqual([r['status'] for r in rows],['propose','not_started','not_started'])
        for r in rows[1:]:
            self.assertEqual((r['model_calls'],r['response']['code'],r['response']['attribution']['failure_class']),(0,'recovery_cutoff_passed','start_refused'))
            self.assertEqual(r['ledger_before']['sequence'],r['ledger_after']['sequence'])
        s=self.f.ledger.summary()
        self.assertEqual((s['count_requests'],s['buckets']['test']['entries']),(1,1))  # only the started row reserved
        self.assertEqual(self.f.paths.count('/v1/responses'),1);self.assertEqual(out['terminal_counts'],{'propose':1,'not_started':2})

    def test_http_serving_has_no_operator_cutoff(self):
        request=self.f.request('Profile median age in House28.');self.f.decisions.append(self.f.decision(self.f.plan('custom')))
        os.environ.pop(ENV,None)
        with patch.object(self.op,'_now',lambda:4102444800.0):  # far past any cutoff; HTTP never consults it
            out=self.f.finish_http(request)
        self.assertEqual(out['status'],'propose')
        import districtbrief.ia_language_jobs as jobs,public_app
        for module in (jobs,public_app):self.assertNotIn(ENV,Path(module.__file__).read_text())

if __name__=='__main__':unittest.main()

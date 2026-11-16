"""Asynchronous and session failures with injected transport, no provider access."""
import copy
import io
import json
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from public_app import Application,load_core
from districtbrief.investigation import Investigation
from districtbrief.ia_language import DISABLED_MESSAGE,EMPTY_PLAN,SCHEMA_VERSION
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import OpenAIProvider
from language_funding_fixture import PROFILE,ledger_fixture,usage
import test_ia_language_contract as contract_fixtures

class LanguageJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ledger=ledger_fixture(self.tmp.name)
        self.entered=threading.Event();self.release=threading.Event();self.transports=[]
        decision={'status':'uncertain','intent':'none','plan':copy.deepcopy(EMPTY_PLAN),'focus_alias':'','clarify_field':'','clarify_choices':[],'reason_code':'uncertain_interpretation','inherited_fields':[]}
        def transport(method,path,body,secret,deadline):
            self.transports.append(path)
            if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':1000}
            self.entered.set();self.release.wait(3)
            return 200,{'model':'gpt-6.1-terra','service_tier':'default','reasoning':{'effort':'medium'},'status':'completed','usage':usage(),
                'output':[{'type':'function_call','name':'ia_language_decision','status':'completed','arguments':json.dumps(decision)}]}
        self.provider=OpenAIProvider(transport=transport,secret_reader=lambda:'fake-no-network')
        self.service=LanguageService(self.i,enabled=True,provider=self.provider,ledger=self.ledger)
    def tearDown(self):
        self.release.set();self.service.close()
        # Wait for bounded injected work to settle before removing its private temporary ledger.
        if self.service._executor:self.service._executor.shutdown(wait=True)
        self.tmp.cleanup()
    def request(self):
        h=contract_fixtures.LanguageContractTests();h.i=self.i;return h.request()
    def poll(self,action,rid,session='a'):
        return self.service.handle(action,{'schema_version':SCHEMA_VERSION,'request_id':rid},session)
    def test_disabled_inert_before_any_credential_network_or_ledger_access(self):
        service=LanguageService(self.i)
        with patch('socket.getaddrinfo',side_effect=AssertionError('DNS')),patch('districtbrief.ia_language_provider.read_secret',side_effect=AssertionError('secret')),patch('districtbrief.ia_language_accounting.BudgetLedger.approval',side_effect=AssertionError('ledger')):
            for action in ('start','status','cancel'):
                code,out=service.handle(action,{},'a');self.assertEqual(code,503);self.assertEqual(out['message'],DISABLED_MESSAGE);self.assertEqual(out['model_calls'],0)
            self.assertFalse(service.bootstrap()['enabled']);self.assertIsNone(service._executor)
    def test_start_status_cancel_fast_while_pending(self):
        r=self.request();begin=time.monotonic();code,out=self.service.handle('start',r,'a')
        self.assertEqual(code,202);self.assertLess(time.monotonic()-begin,1);self.assertTrue(self.entered.wait(1))
        for action in ('status','cancel'):
            begin=time.monotonic();code,out=self.poll(action,r['request_id']);self.assertEqual(code,200);self.assertLess(time.monotonic()-begin,.25)
        self.release.set();self.service._executor.shutdown(wait=True)
        code,out=self.poll('status',r['request_id']);self.assertEqual(out['status'],'cancelled');self.assertEqual(out['model_calls'],1)
        self.assertFalse(self.ledger.summary()['unresolved']);self.assertEqual(self.ledger.summary()['buckets']['demo']['settled_usage_estimate_nano_usd'],1500000)
    def test_no_queue_duplicate_foreign_and_cancel_tombstone(self):
        r=self.request();self.assertEqual(self.service.handle('start',r,'a')[0],202);self.assertTrue(self.entered.wait(1))
        self.assertEqual(self.service.handle('start',r,'a')[0],409)
        self.assertEqual(self.service.handle('start',r,'b')[0],403)
        self.assertEqual(self.service.handle('start',self.request(),'a')[0],409)
        self.assertEqual(self.poll('status',r['request_id'],'b')[0],403);self.assertEqual(self.poll('cancel',r['request_id'],'b')[0],403)
        tombstone=self.request();self.assertEqual(self.poll('cancel',tombstone['request_id'])[1]['status'],'cancelled')
        self.release.set();self.service._executor.shutdown(wait=True)
        self.assertEqual(self.service.handle('start',tombstone,'a')[0],409)
    def test_timeout_suppresses_result_and_blocks_slot_until_settlement(self):
        r=self.request();self.service.handle('start',r,'a');self.assertTrue(self.entered.wait(1))
        with self.service._lock:self.service._jobs[r['request_id']]['deadline']=time.monotonic()-1
        code,out=self.poll('status',r['request_id']);self.assertEqual(out['status'],'expired')
        self.assertEqual(self.service.handle('start',self.request(),'a')[0],409)
        self.release.set();self.service._executor.shutdown(wait=True)
        self.assertEqual(self.poll('status',r['request_id'])[1]['status'],'expired');self.assertFalse(self.ledger.summary()['unresolved'])
    def test_context_is_immutable_and_new_context_expires_old_terminal(self):
        r=self.request();code,out=self.service.handle('start',r,'a');original=copy.deepcopy(out['context'])
        r['context']['revision']=999;r['utterance']='changed';self.release.set();self.service._executor.shutdown(wait=True)
        old=self.poll('status',r['request_id'])[1];self.assertEqual(old['context'],original);self.assertNotIn('utterance',old)
        # A fresh service avoids shutdown executor for the second asynchronous interpretation.
        self.service._executor=None
        new=self.request();new['context']['revision']=2;self.assertEqual(self.service.handle('start',new,'a')[0],202)
        self.service._executor.shutdown(wait=True);self.assertEqual(self.poll('status',r['request_id'])[1]['status'],'expired')
    def test_main_guided_execution_and_health_stay_responsive(self):
        r=self.request();self.service.handle('start',r,'a');self.assertTrue(self.entered.wait(1))
        with tempfile.TemporaryDirectory() as state:
            app=Application(state,secure_cookie=False);app.language=self.service
            env={'REQUEST_METHOD':'GET','PATH_INFO':'/api/health','QUERY_STRING':'','wsgi.input':io.BytesIO(b''),'HTTP_HOST':'local.test'}
            begin=time.monotonic();body=b''.join(app(env,lambda *a:None));self.assertLess(time.monotonic()-begin,.25);self.assertEqual(json.loads(body)['status'],'ok')
            for h in app.service.metrics.handlers:h.close()
        helper=contract_fixtures.LanguageContractTests();helper.i=self.i;c=helper.request(plan=helper.plan())['context']
        run={'schema_version':'haic-investigation/1','request_id':str(uuid.uuid4()),**{k:c[k]for k in ('case_id','branch_id','revision','snapshot_id','operation_version','recipe_version')},'mode':'run','plan':c['confirmed_plan'],'selected_claim_refs':[],'selected_action_ref':None}
        begin=time.monotonic();self.assertEqual(self.i.handle(run)['status'],'ok');self.assertLess(time.monotonic()-begin,1)
    def test_http_rate_limiter_and_operator_only_test_bucket(self):
        self.release.set()
        r=self.request();r['bucket']='test';self.assertEqual(self.service.handle('start',r,'b')[0],400)  # refused before admission: not counted
        for n in range(3):  # rate hotfix: 3 public starts per rolling 300 s site-wide (was 5 per session / 15 per site per hour)
            r=self.request();self.assertEqual(self.service.handle('start',r,'a')[0],202)
            self.service._jobs[r['request_id']]['done'].wait(1)
        self.assertEqual(self.service.handle('start',self.request(),'a')[0],429)
        r=self.request();self.assertEqual(self.service.operator_start(r)[0],202);self.service.operator_wait(r['request_id'])
        summary=self.ledger.summary();self.assertEqual(summary['buckets']['demo']['entries'],3);self.assertEqual(summary['buckets']['test']['entries'],1)
    def test_terminal_retention_bounded_and_no_import_threads(self):
        self.release.set()
        for n in range(34):
            r=self.request();self.assertEqual(self.service.operator_start(r)[0],202);self.service.operator_wait(r['request_id'])
        self.assertEqual(len(self.service._jobs),32)

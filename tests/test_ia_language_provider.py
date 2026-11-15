"""Actual adapter with fake transport/secret/ledger: no credentials or network."""
import copy
import json
import io
from unittest.mock import patch
import tempfile
import threading
import time
import unittest
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.ia_language import LanguageError,FUNCTION_NAME,EMPTY_PLAN,prepare_request
from districtbrief.ia_language_provider import MODEL,OpenAIProvider,provider_payload
from test_ia_language_accounting import ledger_fixture,usage
from districtbrief.ia_language_accounting import BudgetLedger,MAX_INPUT,reservation
import test_ia_language_contract as contract_fixtures

class LanguageProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ledger=ledger_fixture(self.tmp.name)
        helper=contract_fixtures.LanguageContractTests();helper.i=self.i;self.prepared=prepare_request(helper.request(),self.i,'session')
        self.calls=[];self.secret_reads=0;self.dispatches=0
        self.decision={'status':'uncertain','intent':'none','plan':copy.deepcopy(EMPTY_PLAN),'focus_alias':'','clarify_field':'','clarify_choices':[],'reason_code':'uncertain_interpretation','inherited_fields':[]}
        self.body={'status':'completed','model':MODEL,'service_tier':'default','reasoning':{'effort':'low'},'usage':usage(),
            'output':[{'type':'function_call','name':FUNCTION_NAME,'status':'completed','arguments':json.dumps(self.decision)}]}
    def tearDown(self):self.tmp.cleanup()
    def transport(self,method,path,body,secret,deadline):
        self.calls.append(path)
        if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':1000}
        return 200,copy.deepcopy(self.body)
    def secret(self):self.secret_reads+=1;return 'fake-secret-never-network'
    def dispatch(self):self.dispatches+=1
    def run_provider(self,transport=None,cancel=None,bucket='test',ledger=None):
        return OpenAIProvider(transport=transport or self.transport,secret_reader=self.secret).interpret(self.prepared,ledger or self.ledger,bucket,cancel or threading.Event(),time.monotonic()+25,self.dispatch)
    def test_exact_count_and_generation_token_fields_match_no_proxy_or_retry(self):
        payload,count,stats=provider_payload(self.prepared)
        for k,v in count.items():self.assertEqual(payload[k],v)
        self.assertEqual(payload['max_output_tokens'],2048);self.assertEqual(payload['prompt_cache_options'],{'mode':'explicit'})
        self.assertFalse(payload['store']);self.assertFalse(payload['parallel_tool_calls'])
        self.assertEqual(self.run_provider()[0],self.decision);self.assertEqual(self.calls,['/v1/responses/input_tokens','/v1/responses'])
        self.assertEqual(self.secret_reads,1);self.assertEqual(self.dispatches,1)
        self.assertEqual(self.ledger.summary()['buckets']['test']['settled_usage_estimate_nano_usd'],1500000)
    def test_unknown_usage_retains_hold_and_no_fallback(self):
        self.body.pop('usage')
        with self.assertRaises(LanguageError):self.run_provider()
        self.assertTrue(self.ledger.summary()['unresolved']);self.assertEqual(len(self.calls),2)
        with self.assertRaises(LanguageError):self.run_provider()
        self.assertEqual(len(self.calls),2);self.assertEqual(self.secret_reads,1)
    def test_verified_identity_incomplete_refusal_and_invalid_output_still_settle(self):
        for mutation in ('incomplete','refusal','invalid_output'):
            with self.subTest(mutation=mutation):
                self.tearDown();self.setUp()
                if mutation=='incomplete':self.body['status']='incomplete'
                elif mutation=='refusal':self.body['output']=[{'type':'message','content':[{'type':'refusal','refusal':'hidden'}]}]
                elif mutation=='invalid_output':self.body['output'].append(copy.deepcopy(self.body['output'][0]))
                with self.assertRaises(LanguageError):self.run_provider()
                self.assertFalse(self.ledger.summary()['unresolved']);self.assertEqual(self.ledger.summary()['buckets']['test']['settled_usage_estimate_nano_usd'],1500000)
    def test_identity_mismatch_retains_liability_and_blocks_both_buckets_after_restart(self):
        for mutation in ('model','tier','effort','missing_model','missing_tier','missing_reasoning','malformed_reasoning'):
            for first_bucket in ('test','demo'):
                with self.subTest(mutation=mutation,bucket=first_bucket):
                    self.tearDown();self.setUp()
                    if mutation=='model':self.body['model']='gpt-6-astra'
                    elif mutation=='tier':self.body['service_tier']='priority'
                    elif mutation=='effort':self.body['reasoning']['effort']='high'
                    elif mutation=='missing_model':self.body.pop('model')
                    elif mutation=='missing_tier':self.body.pop('service_tier')
                    elif mutation=='missing_reasoning':self.body.pop('reasoning')
                    else:self.body['reasoning']=None
                    with self.assertRaises(LanguageError) as failure:self.run_provider(bucket=first_bucket)
                    self.assertEqual(failure.exception.code,'provider_identity_mismatch')
                    summary=self.ledger.summary();self.assertTrue(summary['unresolved'])
                    self.assertEqual(summary['buckets'][first_bucket]['settled_usage_estimate_nano_usd'],0)
                    self.assertEqual(summary['buckets'][first_bucket]['held_liability_nano_usd'],reservation(1000))
                    entry=json.loads(self.ledger.path.read_text())['entries'][0]
                    self.assertEqual(entry['state'],'unknown');self.assertIsNone(entry['usage']);self.assertIsNone(entry['settled_estimate_nano_usd'])
                    self.assertEqual(entry['terminal_code'],'provider_identity_mismatch')
                    calls=list(self.calls);secrets=self.secret_reads;dispatches=self.dispatches
                    restarted=BudgetLedger(self.ledger.config_hash,self.tmp.name,protected=False)
                    for bucket in ('test','demo'):
                        with self.assertRaises(LanguageError) as blocked:self.run_provider(bucket=bucket,ledger=restarted)
                        self.assertEqual(blocked.exception.code,'unresolved_liability')
                    self.assertEqual(self.calls,calls);self.assertEqual(self.secret_reads,secrets);self.assertEqual(self.dispatches,dispatches)
    def test_count_limit_never_generates_and_releases_undispatched(self):
        def transport(*args):self.calls.append(args[1]);return 200,{'object':'response.input_tokens','input_tokens':MAX_INPUT+1}
        with self.assertRaises(LanguageError):self.run_provider(transport)
        self.assertEqual(self.calls,['/v1/responses/input_tokens']);self.assertEqual(self.dispatches,0);self.assertFalse(self.ledger.summary()['unresolved'])
    def test_cancel_after_count_no_generation(self):
        cancel=threading.Event()
        def transport(*args):cancel.set();return self.transport(*args)
        with self.assertRaises(LanguageError):self.run_provider(transport,cancel)
        self.assertEqual(self.dispatches,0);self.assertFalse(self.ledger.summary()['unresolved'])
    def test_cancel_after_dispatch_settles_usage(self):
        cancel=threading.Event()
        def transport(*args):
            if args[1]=='/v1/responses':cancel.set()
            return self.transport(*args)
        self.run_provider(transport,cancel);self.assertEqual(self.dispatches,1);self.assertFalse(self.ledger.summary()['unresolved'])
    def test_timeout_after_possible_dispatch_preserves_liability(self):
        def transport(*args):
            if args[1]=='/v1/responses':raise LanguageError('provider_timeout',503)
            return self.transport(*args)
        with self.assertRaises(LanguageError):self.run_provider(transport)
        self.assertTrue(self.ledger.summary()['unresolved'])
    def test_oversized_response_rejected_at_64k_without_echo(self):
        stream=io.BytesIO(b'{\"x\":\"'+b'a'*65536+b'\"}')
        class Response:
            status=200
            def read1(self,n):return stream.read(n)
        class Connection:
            sock=None
            def request(self,*a,**kw):pass
            def getresponse(self):return Response()
            def close(self):pass
        with patch('districtbrief.ia_language_provider.http.client.HTTPSConnection',return_value=Connection()):
            with self.assertRaises(LanguageError) as error:OpenAIProvider._https('POST','/v1/responses',{},'fake',time.monotonic()+1)
        self.assertEqual(error.exception.code,'provider_response_too_large')
    def test_operator_diagnostic_failure_cannot_prevent_known_settlement(self):
        observed=[]
        def failed(event):observed.append(self.ledger.summary());raise OSError('injected diagnostic write failure')
        decision,_=OpenAIProvider(transport=self.transport,secret_reader=self.secret).interpret(self.prepared,self.ledger,'test',threading.Event(),time.monotonic()+25,self.dispatch,diagnostic_sink=failed)
        self.assertEqual(decision,self.decision);self.assertFalse(self.ledger.summary()['unresolved'])
        self.assertEqual(observed[0]['buckets']['test']['settled_usage_estimate_nano_usd'],1500000)
        self.assertEqual(self.dispatches,1)
    def test_operator_diagnostic_whitelist_excludes_headers_hidden_reasoning_and_notes(self):
        events=[];self.body['headers']={'Authorization':'Bearer fake-secret-never-network'};self.body['private_notes']='NOTE_CANARY'
        self.body['output'].append({'type':'reasoning','summary':[{'text':'HIDDEN_REASONING_CANARY'}]})
        OpenAIProvider(transport=self.transport,secret_reader=self.secret).interpret(self.prepared,self.ledger,'test',threading.Event(),time.monotonic()+25,self.dispatch,diagnostic_sink=events.append)
        self.assertEqual(len(events),1);event=events[0]
        self.assertEqual(event['function_name'],FUNCTION_NAME);self.assertEqual(event['function_arguments'],json.dumps(self.decision))
        self.assertTrue(event['identity']['verified']);self.assertEqual(event['settlement'],'known_usage_settled')
        self.assertEqual(event['http_status'],200);self.assertEqual(event['response_status'],'completed');self.assertEqual(event['function_status'],'completed')
        encoded=json.dumps(event)
        for private in ('Authorization','fake-secret-never-network','HIDDEN_REASONING_CANARY','NOTE_CANARY'):self.assertNotIn(private,encoded)
    def test_operator_diagnostic_redacts_exact_secret_even_in_invalid_arguments(self):
        events=[];self.decision['invalid_extra']='fake-secret-never-network';self.body['output'][0]['arguments']=json.dumps(self.decision)
        OpenAIProvider(transport=self.transport,secret_reader=self.secret).interpret(self.prepared,self.ledger,'test',threading.Event(),time.monotonic()+25,self.dispatch,diagnostic_sink=events.append)
        self.assertEqual(events[0]['argument_capture'],'captured_secret_redacted');self.assertNotIn('fake-secret-never-network',json.dumps(events))
        self.assertFalse(self.ledger.summary()['unresolved'])
    def test_disallowed_network_route_rejects_before_connection(self):
        with self.assertRaises(LanguageError):OpenAIProvider._https('POST','https://evil.test',{},'fake',time.monotonic()+1)

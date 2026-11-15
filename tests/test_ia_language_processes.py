"""Separate-process CLI/HTTP financial authority checks with injected providers."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from public_app import Application
from districtbrief.ia_language import EMPTY_PLAN,SCHEMA_VERSION
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import OpenAIProvider
from test_ia_language_accounting import ledger_fixture
import test_ia_language_contract as contract_fixtures

CHILD='''import json,os,sys,time
from districtbrief.ia_language_accounting import BudgetLedger
from districtbrief.ia_language import LanguageError
b=BudgetLedger('sha256:'+'a'*64,sys.argv[1],protected=False)
mode=sys.argv[2]
if mode=='hold':
 fd=b.acquire_job();print(json.dumps({'state':'locked','pid':os.getpid()}),flush=True);sys.stdin.read(1);b.release_job(fd)
elif mode=='try':
 t=time.monotonic()
 try:
  fd=b.acquire_job();b.release_job(fd);result='admitted'
 except LanguageError as e:result=e.code
 print(json.dumps({'state':result,'elapsed':time.monotonic()-t,'pid':os.getpid()}))
else:
 e=b.reserve('test','hash');b.counted(e,1000);b.dispatched(e);b.unknown(e,'injected_unknown')
 result={}
 for bucket in ('test','demo'):
  try:b.reserve(bucket,'hash');result[bucket]='admitted'
  except LanguageError as e:result[bucket]=e.code
 print(json.dumps(result))
'''

class LanguageProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ledger=ledger_fixture(self.tmp.name)
        self.app=Application(str(Path(self.tmp.name)/'state'),secure_cookie=False)
        self.entered=threading.Event();self.release=threading.Event()
        outer=self
        class Blocking:
            def interpret(self,p,ledger,bucket,cancel,deadline,on_dispatch):
                outer.entered.set();outer.release.wait(3)
                return {'status':'uncertain','intent':'none','plan':copy.deepcopy(EMPTY_PLAN),'focus_alias':'','clarify_field':'','clarify_choices':[],'reason_code':'uncertain_interpretation','inherited_fields':[]},{}
        self.service=LanguageService(self.app.investigation,enabled=True,ledger=self.ledger,provider=Blocking());self.app.language=self.service
        _,headers,_=self.http('/api/catalog');self.cookie=headers['Set-Cookie'].split(';')[0]
    def tearDown(self):
        self.release.set();self.service.close()
        if self.service._executor:self.service._executor.shutdown(wait=True)
        for h in self.app.service.metrics.handlers:h.close()
        self.tmp.cleanup()
    def http(self,path,body=None):
        raw=json.dumps(body).encode()if body is not None else b'';seen=[]
        env={'REQUEST_METHOD':'POST'if body is not None else'GET','PATH_INFO':path,'QUERY_STRING':'','HTTP_HOST':'local.test',
            'HTTP_COOKIE':getattr(self,'cookie',''),'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)}
        data=b''.join(self.app(env,lambda status,headers:seen.extend([int(status.split()[0]),dict(headers)])))
        return seen[0],seen[1],json.loads(data)
    def request(self):
        helper=contract_fixtures.LanguageContractTests();helper.i=self.app.investigation;return helper.request()
    def child(self,mode):
        return subprocess.run([sys.executable,'-c',CHILD,self.tmp.name,mode],capture_output=True,text=True,timeout=3,check=True)
    def test_cli_process_blocks_real_http_and_http_blocks_other_cli_process(self):
        child=subprocess.Popen([sys.executable,'-c',CHILD,self.tmp.name,'hold'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            state=json.loads(child.stdout.readline());self.assertEqual(state['state'],'locked');self.assertNotEqual(state['pid'],os.getpid())
            started=time.monotonic();code,_,out=self.http('/api/language/start',self.request())
            self.assertEqual(code,409);self.assertEqual(out['status'],'busy');self.assertLess(time.monotonic()-started,1);self.assertIsNone(self.service._active)
            child.communicate('x',timeout=3);self.assertEqual(child.returncode,0)
        finally:
            if child.poll() is None:child.kill();child.communicate()
        request=self.request();self.assertEqual(self.http('/api/language/start',request)[0],202);self.assertTrue(self.entered.wait(1))
        result=json.loads(self.child('try').stdout);self.assertEqual(result['state'],'busy');self.assertLess(result['elapsed'],.25);self.assertNotEqual(result['pid'],os.getpid())
    def test_unknown_liability_in_cli_survives_exit_and_blocks_both_http_and_cli(self):
        result=json.loads(self.child('unknown').stdout);self.assertEqual(result,{'test':'unresolved_liability','demo':'unresolved_liability'})
        before=self.ledger.path.read_bytes();access=[]
        self.service.provider=OpenAIProvider(transport=lambda *a:access.append('network'),secret_reader=lambda:access.append('secret'))
        request=self.request();code,_,out=self.http('/api/language/start',request);self.assertEqual(code,202)
        self.service._jobs[request['request_id']]['done'].wait(1)
        code,_,out=self.http('/api/language/status',{'schema_version':SCHEMA_VERSION,'request_id':request['request_id']})
        self.assertEqual(out['status'],'error');self.assertEqual(out['model_calls'],0);self.assertEqual(access,[]);self.assertEqual(self.ledger.path.read_bytes(),before)
    def test_actual_disabled_startup_health_and_http_do_not_touch_provider(self):
        with patch('socket.getaddrinfo',side_effect=AssertionError('DNS')),patch('districtbrief.ia_language_provider.read_secret',side_effect=AssertionError('secret')),patch('districtbrief.ia_language_accounting.BudgetLedger.approval',side_effect=AssertionError('ledger')):
            disabled=Application(str(Path(self.tmp.name)/'disabled'),secure_cookie=False)
            old=self.app;self.app=disabled
            try:
                self.cookie='';code,headers,out=self.http('/api/catalog');self.cookie=headers['Set-Cookie'].split(';')[0]
                self.assertFalse(out['language']['enabled']);self.assertEqual(self.http('/api/health')[0],200)
                for route in ('start','status','cancel'):
                    code,_,out=self.http('/api/language/'+route,{});self.assertEqual(code,503);self.assertEqual(out['model_calls'],0)
                self.assertIsNone(disabled.language._executor)
            finally:
                for h in disabled.service.metrics.handlers:h.close()
                self.app=old

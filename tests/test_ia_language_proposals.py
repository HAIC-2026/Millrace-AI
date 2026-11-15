"""End-to-end async proposals through WSGI and operator CLI, using fake provider I/O."""
from __future__ import annotations
import os
import time
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from contextlib import redirect_stdout
from unittest.mock import patch
from public_app import Application
from districtbrief.case_contract import admitted_recipes
from districtbrief.ia_language import EMPTY_PLAN,SCHEMA_VERSION,convert_decision,wire_plan
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import OpenAIProvider
from districtbrief.interpret import recipe,food_assistance_recipe
from test_ia_language_accounting import ledger_fixture,usage

class LanguageProposalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ledger=ledger_fixture(str(self.root))
        self.app=Application(str(self.root/'state'),secure_cookie=False)
        self.i=self.app.investigation;self.decisions=[];self.paths=[];self.secret_reads=0
        self.main_thread=threading.get_ident();self.dto_snapshots=[]
        def transport(method,path,body,secret,deadline):
            self.paths.append(path)
            if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':1000}
            decision=self.decisions.pop(0)
            return 200,{'model':'gpt-6.1-terra','service_tier':'default','reasoning':{'effort':'low'},
                'status':'completed','usage':usage(),'output':[{'type':'function_call','name':'ia_language_decision',
                'status':'completed','arguments':json.dumps(decision)}]}
        def secret():self.secret_reads+=1;return 'injected-no-network'
        self.provider=OpenAIProvider(transport=transport,secret_reader=secret)
        self.service=LanguageService(self.i,enabled=True,ledger=self.ledger,provider=self.provider)
        self.app.language=self.service
        _,headers,_=self.http('/api/catalog');self.cookie=headers['Set-Cookie'].split(';')[0]
    def tearDown(self):
        self.service.close()
        if self.service._executor:self.service._executor.shutdown(wait=True)
        for h in self.app.service.metrics.handlers:h.close()
        self.tmp.cleanup()
    def http(self,path,body=None):
        raw=json.dumps(body).encode()if body is not None else b'';seen=[]
        env={'REQUEST_METHOD':'POST'if body is not None else'GET','PATH_INFO':path,'QUERY_STRING':'','HTTP_HOST':'local.test',
            'HTTP_COOKIE':getattr(self,'cookie',''),'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)}
        data=b''.join(self.app(env,lambda status,headers:seen.extend([int(status.split()[0]),dict(headers)])))
        return seen[0],seen[1],json.loads(data)
    def plan(self,kind):
        district={'state_fips':'15','chamber':'house','code':'028','boundary_session':2024}
        if kind=='aging':return recipe(district)
        if kind=='food':return food_assistance_recipe(district)
        return {'district':district,'map_session':2026,'issue_id':'custom','service_area_id':None,
            'steps':[{'step_id':'s1','operation':'profile','args':{'metric_ids':['median_age']}}]}
    def request(self,question,confirmed=None):
        return {'schema_version':SCHEMA_VERSION,'request_id':str(uuid.uuid4()),'utterance':question,'context':{
            **{k:str(uuid.uuid4())for k in ('case_id','branch_id')},'revision':1,'snapshot_id':self.i.snapshot_id,
            'operation_version':'ia-core/1','recipe_version':confirmed['issue_id']+'/1'if confirmed else'custom/1',
            'confirmed_plan':copy.deepcopy(confirmed),'draft_plan':copy.deepcopy(confirmed),'focused_step_id':None,'selected_claim_refs':[]}}
    def decision(self,plan=None,*,intent='create_plan',focus=''):
        return {'status':'propose','intent':intent,'plan':wire_plan(plan)if plan else copy.deepcopy(EMPTY_PLAN),
            'focus_alias':focus,'clarify_field':'','clarify_choices':[],'reason_code':'','inherited_fields':[]}
    def select(self,request):
        c=request['context'];run={'schema_version':'haic-investigation/1','request_id':str(uuid.uuid4()),
            **{k:c[k]for k in ('case_id','branch_id','revision','snapshot_id','operation_version','recipe_version')},
            'mode':'run','plan':c['confirmed_plan'],'selected_claim_refs':[],'selected_action_ref':None}
        result=self.i.handle(run);c['selected_claim_refs']=[result['claims'][0]['claim_ref']];return request
    def finish_http(self,request):
        code,_,start=self.http('/api/language/start',request);self.assertEqual(code,202,start)
        self.assertTrue(self.service._jobs[request['request_id']]['done'].wait(2))
        code,_,out=self.http('/api/language/status',{'schema_version':SCHEMA_VERSION,'request_id':request['request_id']})
        self.assertEqual(code,200);self.assertEqual(out['context'],request['context']);self.assertEqual(out['tokens']['snapshot_id'],self.i.snapshot_id)
        self.assertEqual(out['context_digest'],start['context_digest']);self.assertEqual(out['model_calls'],1)
        return out
    def guard_metadata(self):
        original=self.i.core.metadata.has_path
        def checked(path):
            self.assertEqual(threading.get_ident(),self.main_thread,'live metadata reached provider thread')
            return original(path)
        return patch.object(self.i.core.metadata,'has_path',side_effect=checked)
    def checked_convert(self,prepared,decision,validation):
        self.assertNotEqual(threading.get_ident(),self.main_thread)
        self.assertFalse(hasattr(validation,'metadata'))
        self.assertIsInstance(validation.admitted_recipe_versions,tuple)
        self.assertEqual(validation.admitted_recipe_versions,tuple(prepared['provider_context']['catalog']['recipes']))
        self.dto_snapshots.append(validation.admitted_recipe_versions)
        return convert_decision(prepared,decision,validation)
    def test_actual_http_custom_default_and_food_plan_proposals(self):
        with self.guard_metadata(),patch('districtbrief.ia_language_jobs.convert_decision',side_effect=self.checked_convert):
            for kind,question in [('custom','Profile median age in House28.'),('aging','Aging at home in House28.'),('food','SNAP outreach in House28.')]:
                with self.subTest(kind=kind):
                    plan=self.plan(kind);self.decisions.append(self.decision(plan));out=self.finish_http(self.request(question))
                    if kind=='food' and 'food_assistance_outreach/1' not in admitted_recipes(self.i.core):
                        self.assertEqual(out['status'],'uncertain');self.assertNotIn('normalized_plan',out)
                    else:
                        self.assertEqual(out['status'],'propose');self.assertEqual(out['normalized_plan'],plan)
                        self.assertEqual(out['intent'],'create_plan');self.assertTrue(out['typed_diff'])
        self.assertEqual(len(self.dto_snapshots),3);self.assertFalse(self.ledger.summary()['unresolved'])
        self.assertEqual(self.ledger.summary()['buckets']['demo']['entries'],3)
    def test_actual_http_source_proposal_and_selected_context(self):
        request=self.select(self.request('Why that figure?',self.plan('aging')))
        self.decisions.append(self.decision(intent='inspect_source',focus='selected_1'))
        with self.guard_metadata(),patch('districtbrief.ia_language_jobs.convert_decision',side_effect=self.checked_convert):out=self.finish_http(request)
        self.assertEqual(out['status'],'propose');self.assertEqual(out['intent'],'inspect_source')
        self.assertIsNone(out['normalized_plan']);self.assertEqual(out['typed_diff'],[]);self.assertTrue(out['source_inspection_refs'])
        self.assertNotIn('answer',out);self.assertNotIn('utterance',out)
    def test_actual_http_edit_proposal_does_not_execute_candidate(self):
        prior=self.plan('aging');request=self.select(self.request('Same for Senate25.',prior))
        proposed=copy.deepcopy(prior);proposed['district'].update(chamber='senate',code='025')
        self.decisions.append(self.decision(proposed,intent='replace_plan'))
        dispatched=[];original=self.i.handle
        def caller_run(r):
            self.assertEqual(threading.get_ident(),self.main_thread)
            self.assertEqual(r['plan'],prior);dispatched.append(r['mode']);return original(r)
        with patch.object(self.i,'handle',side_effect=caller_run),self.guard_metadata():out=self.finish_http(request)
        self.assertEqual(dispatched,['run']);self.assertEqual(out['status'],'propose');self.assertEqual(out['normalized_plan'],proposed)
        district=next(d for d in out['typed_diff']if d['field']=='district')
        self.assertEqual(district['before'],prior['district']);self.assertEqual(district['after'],proposed['district'])
        self.assertIn('steps',out['inherited_fields']);self.assertEqual(out['context']['selected_claim_refs'],request['context']['selected_claim_refs'])
    def test_stale_selected_ref_refuses_http_and_operator_before_provider(self):
        request=self.select(self.request('Why that figure?',self.plan('aging')))
        request['context']['selected_claim_refs'][0]['semantic_hash']='sha256:'+'0'*64
        code,_,out=self.http('/api/language/start',request);self.assertEqual(code,409)
        code,out=self.service.operator_start(request);self.assertEqual(code,409)
        self.assertEqual(self.paths,[]);self.assertEqual(self.secret_reads,0);self.assertEqual(self.ledger.summary()['buckets']['test']['entries'],0)
    def test_explicit_replacement_fourth_source_and_numeric_minimal_over_http(self):
        prior=self.plan('custom');prior['district']['code']='035';prior['map_session']=2024
        prior['steps']=[{'step_id':'s1','operation':'profile','args':{'metric_ids':['unemployment_rate']}},{'step_id':'s2','operation':'program_evidence','args':{'program_ids':['snap_hi']}}]
        expected=copy.deepcopy(prior);expected['district'].update(chamber='senate',code='018')
        self.decisions.append(self.decision(expected,intent='replace_plan'))
        request=self.request('Retain both current steps and the 2024 map, but replace House 35 with Senate 18.',prior);request['context']['draft_plan']=None
        self.assertEqual(self.finish_http(request)['normalized_plan'],expected)
        prior=self.plan('custom');prior['district']['code']='036';prior['steps']=[{'step_id':f's{n+1}','operation':'profile','args':{'metric_ids':[metric]}}for n,metric in enumerate(list(self.i.core.metrics)[:8])]
        request=self.request('Inspect only the fourth selected finding source. Keep the investigation unchanged.',prior);request['context']['draft_plan']=None
        c=request['context'];run={'schema_version':'haic-investigation/1','request_id':str(uuid.uuid4()),**{k:c[k]for k in ('case_id','branch_id','revision','snapshot_id','operation_version','recipe_version')},'mode':'run','plan':prior,'selected_claim_refs':[],'selected_action_ref':None}
        claims=self.i.handle(run)['claims'];c['selected_claim_refs']=[x['claim_ref']for x in claims[:8]]
        self.decisions.append(self.decision(intent='inspect_source',focus='selected_4'))
        out=self.finish_http(request);self.assertEqual(out['source_inspection_refs'],claims[3]['source_inspection_refs'])
        expected=self.plan('custom');expected['district'].update(chamber='senate',code='016');expected['steps'][0]['args']['metric_ids']=['total_housing_units']
        decision=self.decision(expected);decision['plan']['map_session']=2026.0;self.decisions.append(decision)
        self.assertEqual(self.finish_http(self.request('Make one total-housing-units profile for Senate district 16.'))['normalized_plan'],expected)
    @patch.dict(os.environ,{'HAIC_LANGUAGE_OPERATOR_CUTOFF_EPOCH':str(int(time.time())+86400)})  # evaluator-supplied future cutoff
    def test_actual_operator_cli_custom_default_food_source_and_edit_proposals(self):
        requests=[];plans=[];expected=[]
        for kind,question in [('custom','Profile median age in House28.'),('aging','Aging at home in House28.'),('food','SNAP outreach in House28.')]:
            plan=self.plan(kind);requests.append(self.request(question));plans.append(plan)
            self.decisions.append(self.decision(plan));expected.append('uncertain'if kind=='food'and 'food_assistance_outreach/1'not in admitted_recipes(self.i.core)else'propose')
        source=self.select(self.request('Why that figure?',self.plan('aging')))
        requests.append(source);plans.append(None);expected.append('propose');self.decisions.append(self.decision(intent='inspect_source',focus='selected_1'))
        prior=self.plan('aging');edit=self.select(self.request('Same for Senate25.',prior));proposed=copy.deepcopy(prior);proposed['district'].update(chamber='senate',code='025')
        requests.append(edit);plans.append(proposed);expected.append('propose');self.decisions.append(self.decision(proposed,intent='replace_plan'))
        questions=self.root/'questions.jsonl';output=self.root/'results.jsonl'
        questions.write_text(''.join(json.dumps({'case_id':f'own-{n}','request':r})+'\n'for n,r in enumerate(requests)))
        tool=Path(__file__).resolve().parents[1]/'tools/ia_language_operator.py'
        spec=importlib.util.spec_from_file_location('ia_operator_proposal_test',tool);operator=importlib.util.module_from_spec(spec);spec.loader.exec_module(operator)
        # Only mount/approval location seams are injected. The actual CLI parser, request
        # validator, adapter, job slot, converter and durable ledger run unchanged.
        with patch.object(operator,'load_core',return_value=self.i.core),patch.object(operator,'BudgetLedger',return_value=self.ledger),\
             patch.object(operator,'protected_path',side_effect=lambda path,**kw:Path(path)),\
             patch('districtbrief.ia_language_jobs.OpenAIProvider',return_value=self.provider),\
             patch('districtbrief.ia_language_jobs.convert_decision',side_effect=self.checked_convert),self.guard_metadata(),redirect_stdout(io.StringIO()):
            code=operator.main(['smoke','--questions',str(questions),'--output',str(output)])
        self.assertEqual(code,0);rows=[json.loads(line)for line in output.read_text().splitlines()]
        self.assertEqual(len(rows),5);self.assertEqual([r['status']for r in rows],expected)
        for n,row in enumerate(rows):
            self.assertEqual(row['bucket'],'test');self.assertEqual(row['model_calls'],1)
            if expected[n]=='propose':self.assertEqual(row['response']['normalized_plan'],plans[n])
            self.assertEqual(row['response']['context'],requests[n]['context'])
        self.assertTrue(rows[3]['response']['source_inspection_refs']);self.assertEqual(len(self.dto_snapshots),5)
        summary=self.ledger.summary();self.assertEqual(summary['buckets']['test']['entries'],5);self.assertEqual(summary['buckets']['demo']['entries'],0);self.assertFalse(summary['unresolved'])

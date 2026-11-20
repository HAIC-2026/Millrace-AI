"""Proposal map_session 0 (unstated) resolution, replayed from the three actual saved DEV
qualification responses. Offline replay is carry evidence only, never live model credit."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.interpret import recipe
from districtbrief.ia_language import (EMPTY_PLAN,LanguageError,NEW_PLAN_MAP_SESSION,SCHEMA_VERSION,convert_decision,
    dumps,ordinary_plan,prepare_request,strict_json,wire_plan)
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import PROMPT,OpenAIProvider,provider_payload
from language_funding_fixture import HISTORICAL_LOW,PROFILE,ledger_fixture,rebind_saved_requests,usage

FIXTURE=json.loads((Path(__file__).parent/'fixtures'/'ia-language-dev-v5-replay.json').read_text())
CASES={c['case_id']:c for c in FIXTURE['cases']}
MINIMAL=CASES['qualification-minimal']

def provider_usage(u):
    return usage(u['input_tokens'],u['output_tokens'],u['cached_input_tokens'],u['cache_write_tokens'],u['reasoning_tokens_within_output'])

class MapDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core());rebind_saved_requests(FIXTURE,cls.i)
    def prepared(self,utterance=None,confirmed=None,draft=None,base=MINIMAL):
        r=copy.deepcopy(base['request'])
        if utterance is not None:r['utterance']=utterance
        if confirmed is not None or draft is not None:
            r['context'].update(confirmed_plan=copy.deepcopy(confirmed),draft_plan=copy.deepcopy(draft),
                recipe_version=(confirmed or draft)['issue_id']+'/1')
        return prepare_request(r,self.i,'session')
    def raw(self,case=MINIMAL,**plan):
        d=strict_json(case['function_arguments']);d['plan'].update(plan);return d
    def convert(self,p,d):return convert_decision(p,d,self.i.core)
    def plan(self,map_session):
        return {'district':{'state_fips':'15','chamber':'senate','code':'016','boundary_session':2024},'map_session':map_session,
            'issue_id':'custom','service_area_id':None,'steps':[{'step_id':'s1','operation':'profile','args':{'metric_ids':['total_housing_units']}}]}

    def assert_replay_tokens(self,tokens,expected):
        # Saved branch tokens stay exact; software identity belongs to the running artifact.
        release_id='sha256:'+hashlib.sha256((Path(__file__).resolve().parents[1]/'RELEASE-MANIFEST.json').read_bytes()).hexdigest()
        self.assertEqual(self.i.bootstrap()['release_id'],release_id)
        self.assertEqual(tokens,{**expected,'release_id':release_id})

    @staticmethod
    def pre_v10_comparators(request,geographies):
        # Historical (v1-v8) comparator-choice rule, reproduced only to verify the settled V5 payload bytes.
        import re
        u=request['utterance'];c=request['context']
        out={g for g in geographies if not re.search(r'-(?:HOUSE|SENATE)-',g)}
        for plan in (c['confirmed_plan'],c['draft_plan']):
            if plan:out.update(s['args']['comparison_geography'] for s in plan['steps'] if s['operation']=='compare' and s['args']['comparison_geography'] in geographies)
        for m in re.finditer(r'\b(house|senate)\s*(?:district\s*)?0*(\d{1,2})\b',u,re.I):out.add(f'HI-{m.group(1).upper()}-{int(m.group(2)):03}-2024')
        low=u.lower()
        for m in re.finditer(r'\bdistrict\s*(?:#\s*|no\.?\s*|number\s+)?0*(\d{1,2})\b',low):
            if not re.search(r'\b(?:house|senate)\s*$',low[:m.start()]):out.update(f'HI-{c}-{int(m.group(1)):03}-2024' for c in ('HOUSE','SENATE'))
        return out&set(geographies)

    def test_saved_raw_three_cases_exact_expected_and_unchanged_outbound_payload(self):
        # The settled V5/V8 requests used the preserved V8 prompt; this repair changes only the instructions text.
        v8_prompt=(Path(__file__).parent/'fixtures/ia-language-prompt-v8.txt').read_text(encoding='utf-8')
        self.assertEqual(hashlib.sha256(v8_prompt.encode()).hexdigest(),'52f5718dc159fa4842e42e55935feafaae23b303b6e9e771dcd453d8f7dcab33')
        self.assertNotEqual(PROMPT,v8_prompt)
        for case in FIXTURE['cases']:
            p=prepare_request(case['request'],self.i,'session')
            self.assertEqual(p['catalog_digest'],FIXTURE['first_adoption_record']['catalog_digest'])
            # Byte-identical outbound payload to the actually settled V5 request when only the V8 prompt and the
            # pre-v10 comparator-clarification universe are restored (v10 offers every admitted geography).
            replay=copy.deepcopy(provider_payload(p,HISTORICAL_LOW)[0]);replay['instructions']=v8_prompt
            enum=replay['tools'][0]['parameters']['properties']['clarify_choices']['items']['enum']
            self.assertTrue(all('g_'+g in enum for g in p['provider_context']['catalog']['geographies']))  # v10 full universe
            allowed=self.pre_v10_comparators(case['request'],p['provider_context']['catalog']['geographies'])
            enum[:]=[a for a in enum if not (a.startswith('g_') and a[2:] not in allowed)]
            self.assertEqual('sha256:'+hashlib.sha256(dumps(replay)).hexdigest(),case['settled_entry']['payload_hash'])
            self.assertEqual(p['schema']['properties']['plan']['properties']['map_session'],{'type':'integer','enum':[0,2024,2026]})
            out=self.convert(p,strict_json(case['function_arguments']));e=case['expected']
            self.assertEqual((out['status'],out['intent'],out['normalized_plan']),(e['status'],e['intent'],e['normalized_plan']))
            self.assertEqual(out['source_inspection_refs'],e.get('source_inspection_refs',[]));self.assert_replay_tokens(p['tokens'],e['bound_tokens'])
        out=self.convert(self.prepared(),self.raw())
        self.assertEqual(out['normalized_plan']['map_session'],2026);self.assertEqual(out['normalized_plan']['district']['boundary_session'],2024)
        self.assertIn({'field':'map_session','change':'added','before':None,'after':2026},out['typed_diff']);self.assertEqual(out['inherited_fields'],[])

    def test_saved_raw_through_actual_job_adapter_and_settled_cost(self):
        for case in FIXTURE['cases']:
            with tempfile.TemporaryDirectory() as tmp:
                ledger=ledger_fixture(tmp);calls=[]
                def transport(method,path,body,secret,deadline,case=case):
                    calls.append(path)
                    if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':case['usage']['input_tokens']}
                    return 200,{'model':'gpt-6.1-terra','service_tier':'default','reasoning':{'effort':'medium'},'status':'completed',
                        'usage':provider_usage(case['usage']),'output':[{'type':'function_call','name':'ia_language_decision','status':'completed','arguments':case['function_arguments']}]}
                service=LanguageService(self.i,enabled=True,provider=OpenAIProvider(transport=transport,secret_reader=lambda:'fake-no-network'),ledger=ledger)
                try:
                    code,_=service.handle('start',copy.deepcopy(case['request']),'a');self.assertEqual(code,202)
                    for _ in range(200):
                        code,out=service.handle('status',{'schema_version':SCHEMA_VERSION,'request_id':case['request']['request_id']},'a')
                        if out['status']!='pending':break
                        time.sleep(.02)
                finally:
                    service.close()
                    if service._executor:service._executor.shutdown(wait=True)
                e=case['expected']
                self.assertEqual((out['status'],out['intent'],out['normalized_plan']),(e['status'],e['intent'],e['normalized_plan']),case['case_id'])
                self.assert_replay_tokens(out['tokens'],e['bound_tokens']);self.assertEqual(len(calls),2)
                s=ledger.summary();self.assertEqual(s['count_requests'],1)
                self.assertEqual(s['buckets']['demo']['settled_usage_estimate_nano_usd']+s['buckets']['test']['settled_usage_estimate_nano_usd'],
                    case['settled_entry']['settled_estimate_nano_usd'])

    def job(self,request,arguments,decision_override=None):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=ledger_fixture(tmp)
            def transport(method,path,body,secret,deadline):
                if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':8000}
                return 200,{'model':'gpt-6.1-terra','service_tier':'default','reasoning':{'effort':'medium'},'status':'completed',
                    'usage':usage(8000,100),'output':[{'type':'function_call','name':'ia_language_decision','status':'completed','arguments':arguments}]}
            service=LanguageService(self.i,enabled=True,provider=OpenAIProvider(transport=transport,secret_reader=lambda:'fake-no-network'),ledger=ledger)
            try:
                self.assertEqual(service.handle('start',request,'a')[0],202)
                for _ in range(200):
                    out=service.handle('status',{'schema_version':SCHEMA_VERSION,'request_id':request['request_id']},'a')[1]
                    if out['status']!='pending':return out
                    time.sleep(.02)
            finally:
                service.close()
                if service._executor:service._executor.shutdown(wait=True)

    def test_map_refusals_are_uncertain_through_job_and_internal_failure_stays_error(self):
        # FH A-4: contract ambiguity/mismatch is uncertain, not a service failure.
        def req(text,draft=None):
            r=copy.deepcopy(MINIMAL['request']);r['request_id']=str(__import__('uuid').uuid4());r['utterance']=text
            if draft:r['context'].update(draft_plan=draft)
            return r
        for r,wire in ((req('Senate 16 housing units on the 2024 map versus the 2026 map.'),0),
                       (req('Make one total-housing-units profile for Senate district 16.',self.plan(2024)),2026),
                       (req('Switch this Senate 16 plan from the 2024 map to the 2026 map.'),2024)):
            out=self.job(r,json.dumps(self.raw(map_session=wire)))
            self.assertEqual((out['status'],out['reason_code'],out['model_calls']),('uncertain','uncertain_interpretation',1))
        out=self.job(req('Switch this Senate 16 plan from the 2024 map to the 2026 map.'),json.dumps(self.raw(map_session=2026)))
        self.assertEqual((out['status'],out['normalized_plan']['map_session']),('propose',2026))
        with patch('districtbrief.ia_language_jobs.convert_decision',side_effect=LanguageError('accounting_unavailable',503)):
            self.assertEqual(self.job(req('Make one total-housing-units profile for Senate district 16.'),MINIMAL['function_arguments'])['status'],'error')

    def test_inherited_map_label_through_service(self):
        # Period-only wording keeps an honestly inherited confirmed map; explicit change and no-context default never claim it.
        def run(text,confirmed,wire):
            r=copy.deepcopy(MINIMAL['request']);r['request_id']=str(__import__('uuid').uuid4());r['utterance']=text
            d=self.raw(map_session=wire)
            if confirmed:
                r['context'].update(confirmed_plan=copy.deepcopy(confirmed),draft_plan=copy.deepcopy(confirmed),recipe_version='custom/1')
                d.update(intent='replace_plan',plan=wire_plan(confirmed));d['plan']['map_session']=wire
            return self.job(r,json.dumps(d))
        for year in (2024,2026):
            out=run('Make one total-housing-units profile for Senate district 16 using ACS 2020\u20132024.',self.plan(year),0)
            self.assertEqual((out['status'],out['normalized_plan']['map_session']),('propose',year));self.assertIn('map_session',out['inherited_fields'])
        out=run('Switch this plan from the 2024 map to the 2026 map using ACS 2020\u20132024.',self.plan(2024),2026)
        self.assertEqual(out['normalized_plan']['map_session'],2026);self.assertNotIn('map_session',out['inherited_fields'])
        out=run('Make one total-housing-units profile for Senate district 16 using ACS 2020\u20132024.',None,0)
        self.assertEqual((out['normalized_plan']['map_session'],out['inherited_fields']),(2026,[]))

    def test_explicit_map_overrides_and_conflicts(self):
        u='Make one total-housing-units profile for Senate district 16 on the {} map.'
        for year in (2024,2026):
            with self.assertRaises(LanguageError) as c:self.convert(self.prepared(u.format(year)),self.raw())
            self.assertEqual(c.exception.code,'explicit_map_unreported')  # stated year + sentinel: never server-filled
            self.assertEqual(self.convert(self.prepared(u.format(year)),self.raw(map_session=year))['normalized_plan']['map_session'],year)
            with self.assertRaises(LanguageError) as c:self.convert(self.prepared(u.format(year)),self.raw(map_session=4050-year))
            self.assertEqual(c.exception.code,'explicit_map_conflict')
        for text in ('Senate 16 housing units on the 2024 map versus the 2026 map.','Profile Senate 16 housing on map session 2024 or 2026 map.'):
            for wire in (0,2024,2026):  # undirected two maps: never guessed, even with a nonzero value
                with self.assertRaises(LanguageError) as c:self.convert(self.prepared(text),self.raw(map_session=wire))
                self.assertEqual(c.exception.code,'explicit_map_ambiguous')

    def test_data_period_is_not_map_evidence(self):
        # FH A-1: an admitted ACS period or bare year neither blocks nor selects a map.
        for text in ('Make one total-housing-units profile for Senate district 16 using ACS 2020–2024.',
                     'Profile total housing units for Senate district 16 for 2024.','Senate district 16 housing units in 2026.',
                     'Profile total housing units for Senate district 16 from 2024 to 2026.'):
            for wire in (0,2026):self.assertEqual(self.convert(self.prepared(text),self.raw(map_session=wire))['normalized_plan']['map_session'],2026)
            # FH A-5 closed: an unstated model map year never replaces the held/default map.
            with self.assertRaises(LanguageError) as c:self.convert(self.prepared(text),self.raw(map_session=2024))
            self.assertEqual(c.exception.code,'explicit_map_unstated_change')
        for text in ('Make one total-housing-units profile for Senate district 24.','Profile housing units for Senate 16 on fixed statistical boundaries.'):
            d=self.raw();d['plan']['district']['code']='024' if '24' in text else '016'
            self.assertEqual(self.convert(self.prepared(text),d)['normalized_plan']['map_session'],2026)

    def test_directed_switch_and_negation(self):
        # FH A-2: the target is honored, the source never; FH A-3: an excluded map is not a selection.
        # No-context variants name the district explicitly (F1: a district is never guessed without context).
        cases=[('Switch this Senate 16 plan from the 2024 map to the 2026 map.',2026,2024),('For Senate 16 use the 2026 map instead of the 2024 map.',2026,2024),
               ('Switch this Senate 16 plan from the 2026 map to the 2024 map.',2024,2026),
               ('Profile total housing units for Senate district 16, not on the 2024 map.',2026,2024)]
        for text,target,source in cases:
            self.assertEqual(self.convert(self.prepared(text),self.raw(map_session=target))['normalized_plan']['map_session'],target,text)
            if 'not on' in text:  # exclusion only: no year is selected, the sentinel resolves by the two-map default
                self.assertEqual(self.convert(self.prepared(text),self.raw())['normalized_plan']['map_session'],target,text)
            else:
                with self.assertRaises(LanguageError) as c:self.convert(self.prepared(text),self.raw())
                self.assertEqual(c.exception.code,'explicit_map_unreported',text)
            with self.assertRaises(LanguageError) as c:self.convert(self.prepared(text),self.raw(map_session=source))
            self.assertEqual(c.exception.code,'explicit_map_conflict')
        self.assertEqual(self.convert(self.prepared("Profile Senate 16 housing; don't change the 2024 map."),self.raw(map_session=2024))['normalized_plan']['map_session'],2024)
        with self.assertRaises(LanguageError) as c:self.convert(self.prepared("Profile Senate 16 housing; don't change the 2024 map."),self.raw())
        self.assertEqual(c.exception.code,'explicit_map_unreported')
        with self.assertRaises(LanguageError) as c:self.convert(self.prepared('Profile Senate 16 housing, not on the 2026 map.'),self.raw())
        self.assertEqual(c.exception.code,'explicit_map_conflict')  # default 2026 is excluded: never guess 2024
        confirmed=self.plan(2024);d={**self.raw(),'intent':'replace_plan','plan':wire_plan(confirmed)};d['plan']['map_session']=0
        with self.assertRaises(LanguageError):self.convert(self.prepared('Profile Senate 16 housing units, not on the 2024 map.',confirmed,confirmed),d)
        with self.assertRaises(LanguageError) as c:self.convert(self.prepared('Switch this plan from the 2024 map to the 2026 map.',confirmed,confirmed),d)
        self.assertEqual(c.exception.code,'explicit_map_unreported')
        d['plan']['map_session']=2026;out=self.convert(self.prepared('Switch this plan from the 2024 map to the 2026 map.',confirmed,confirmed),d)
        self.assertEqual(out['normalized_plan']['map_session'],2026);self.assertNotIn('map_session',out['inherited_fields'])

    def test_directed_map_switch_variants_through_service(self):
        # FH N-1: "from" governs the source even when only one side names the map.
        phrases=('Switch the map from {source} to {target}.',
                 'Change the map session from {source} to {target}.',
                 'Switch from the {source} map to {target}.',
                 'Move from the {source} map to the {target} one.')
        for source,target in ((2024,2026),(2026,2024)):
            for phrase in phrases:
                text=phrase.format(source=source,target=target)
                for confirmed in (None,self.plan(source)):
                    for wire in (0,target,source):
                        with self.subTest(text=text,confirmed=bool(confirmed),wire=wire):
                            r=copy.deepcopy(MINIMAL['request']);r['utterance']=text if confirmed else 'For Senate 16: '+text  # F1: no-context names the district
                            d=self.raw(map_session=wire)
                            if confirmed:
                                r['context'].update(confirmed_plan=copy.deepcopy(confirmed),draft_plan=copy.deepcopy(confirmed),recipe_version='custom/1')
                                d.update(intent='replace_plan',plan=wire_plan(confirmed));d['plan']['map_session']=wire
                            out=self.job(r,json.dumps(d))
                            if wire!=target:  # the excluded source, or the sentinel beside a stated target year
                                self.assertEqual((out['status'],out['reason_code']),('uncertain','uncertain_interpretation'))
                                self.assertIsNone(out.get('normalized_plan'))
                            else:
                                self.assertEqual(out['status'],'propose')
                                self.assertEqual(out['normalized_plan']['map_session'],target)
                                self.assertNotIn('map_session',out['inherited_fields'])
                                if confirmed:self.assertIn({'field':'map_session','change':'changed','before':source,'after':target},out['typed_diff'])
                            self.assertEqual(out['model_calls'],1)

    def test_confirmed_map_control_resolves_and_draft_conflicts_refuse(self):
        for year,u in ((2024,'Add a total population profile.'),(2026,'Add a total population profile.'),
                (2024,'Add a total population profile using ACS 2020-2024.'),(2026,'Add a total population profile for 2024.')):
            confirmed=self.plan(year);p=self.prepared(u,confirmed,confirmed)
            d={**strict_json(MINIMAL['function_arguments']),'intent':'replace_plan','plan':wire_plan(confirmed)}
            d['plan']['map_session']=0;d['plan']['steps'].append({'step_id':'s2','operation':'profile','metric_ids':['total_population'],
                'comparison_geography':'','program_ids':[],'observation_ids':[]})
            out=self.convert(p,d);self.assertEqual(out['normalized_plan']['map_session'],year)
            self.assertIn('map_session',out['inherited_fields'])  # period words are not map instructions
            d['inherited_fields']=['map_session'];self.assertEqual(self.convert(p,d)['normalized_plan']['map_session'],year)
        # Draft-only context (OX-L5 held rule): map 0 keeps the visible draft map; an unstated other year is refused.
        self.assertEqual(self.convert(self.prepared(None,None,self.plan(2024)),self.raw())['normalized_plan']['map_session'],2024)
        with self.assertRaises(LanguageError) as c:self.convert(self.prepared(None,None,self.plan(2024)),self.raw(map_session=2026))
        self.assertEqual(c.exception.code,'explicit_map_unstated_change')
        self.assertEqual(self.convert(self.prepared(None,None,self.plan(2026)),self.raw())['normalized_plan']['map_session'],2026)
        # Divergent confirmed/draft map controls are never resolved.
        out=self.convert(self.prepared(None,self.plan(2024),self.plan(2026)),{**self.raw(),'intent':'replace_plan'})
        self.assertEqual((out['status'],out['clarify_field'],out['normalized_plan']),('clarify','control_conflict',None))

    def test_new_plan_default_is_the_existing_contract_default(self):
        d={'state_fips':'15','chamber':'house','code':'028','boundary_session':2024}
        from districtbrief.interpret import food_assistance_recipe,interpret
        self.assertEqual(NEW_PLAN_MAP_SESSION,recipe(d)['map_session']);self.assertEqual(NEW_PLAN_MAP_SESSION,food_assistance_recipe(d)['map_session'])
        # Typed request with no plan creates the same default map session.
        out=interpret('compare senior poverty with state for senate 16',None)
        self.assertEqual(json.dumps(out).count('"map_session": 2026')>=1,True)

    def test_type_guards_and_zero_elsewhere(self):
        out=self.convert(self.prepared(),self.raw(map_session=0.0));self.assertIs(type(out['normalized_plan']['map_session']),int)
        self.assertIs(type(self.convert(self.prepared(),self.raw(map_session=2026.0))['normalized_plan']['map_session']),int)
        self.assertIs(type(self.convert(self.prepared('Senate 16 housing units on the 2024 map.'),self.raw(map_session=2024.0))['normalized_plan']['map_session']),int)
        with self.assertRaises(LanguageError):self.convert(self.prepared(),self.raw(map_session=2024.0))  # unstated
        for bad in (0.5,True,False,'0',None,2025,-0.1,float('nan')):
            with self.assertRaises(LanguageError):self.convert(self.prepared(),self.raw(map_session=bad))
        # The plain helper never defaults: only the converter resolves with context.
        with self.assertRaises(LanguageError):ordinary_plan(self.raw()['plan'],self.i.core)
        p=self.prepared('Profile housing for Senate 16 with deliberately unclear wording.')
        for status,reason,field,choices in (('uncertain','uncertain_interpretation','',[]),('unsupported','unavailable_evidence','',[]),
                ('clarify','missing_context','chamber',['c_house','c_senate'])):
            d={'status':status,'intent':'none','plan':copy.deepcopy(EMPTY_PLAN),'focus_alias':'','clarify_field':field,
               'clarify_choices':choices,'reason_code':reason,'inherited_fields':[]}
            self.assertEqual(self.convert(p,d)['status'],status)
            d['plan']['map_session']=2026
            with self.assertRaises(LanguageError):self.convert(p,d)
        src=CASES['qualification-combined-eight'];ps=prepare_request(src['request'],self.i,'session');d=strict_json(src['function_arguments'])
        self.assertEqual(self.convert(ps,d)['status'],'propose');d['plan']['map_session']=2026
        with self.assertRaises(LanguageError):self.convert(ps,d)

    def test_existing_guards_still_apply_after_resolution(self):
        d=self.raw();d['plan']['district']['code']='017'
        with self.assertRaises(LanguageError):self.convert(self.prepared(),d)  # explicit district conflict
        out=self.convert(self.prepared('Who is eligible for housing in Senate 16?'),self.raw())
        self.assertEqual((out['status'],out['reason_code'],out['normalized_plan']),('unsupported','unsupported_operation',None))
        with self.assertRaises(LanguageError) as c:self.convert(self.prepared('Profile eligibility of housing in Senate 16.'),self.raw())
        self.assertEqual(c.exception.code,'unsupported_inference_unproven')  # bare keyword: uncertain, never a plan
        d=self.raw();d['plan']['steps'][0]['program_ids']=['snap_hi']
        with self.assertRaises(LanguageError):self.convert(self.prepared(),d)

if __name__=='__main__':unittest.main()

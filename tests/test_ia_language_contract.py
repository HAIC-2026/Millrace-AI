"""Offline contract and privacy checks; injected decisions do not measure model quality."""
import copy
import json
from pathlib import Path
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.interpret import recipe
from districtbrief.ia_language import (EMPTY_PLAN,LanguageError,SCHEMA_VERSION,convert_decision,
    decision_schema,dumps,lint_schema,prepare_request,strict_json,value_free_catalog,wire_plan)
from districtbrief.ia_language_provider import provider_payload
from language_funding_fixture import PROFILE

class LanguageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    def request(self,utterance='Compare senior poverty in House28 with the State.',plan=None):
        return {'schema_version':SCHEMA_VERSION,'request_id':str(uuid.uuid4()),'utterance':utterance,'context':{
            **{k:str(uuid.uuid4())for k in ('case_id','branch_id')},'revision':1,'snapshot_id':self.i.snapshot_id,
            'operation_version':'ia-core/1','recipe_version':plan['issue_id']+'/1' if plan else 'custom/1',
            'confirmed_plan':copy.deepcopy(plan),'draft_plan':copy.deepcopy(plan),'focused_step_id':None,'selected_claim_refs':[]}}
    def decision(self,p,plan=None,**kw):
        d={'status':'propose','intent':'replace_plan' if p['context']['confirmed_plan'] else 'create_plan',
            'plan':wire_plan(plan) if plan else copy.deepcopy(EMPTY_PLAN),'focus_alias':'','clarify_field':'',
            'clarify_choices':[],'reason_code':'','inherited_fields':[]};d.update(kw);return d
    def plan(self,chamber='house',code='028',metric='poverty_rate_65_plus',comparator='HI-STATE-2024'):
        return {'district':{'state_fips':'15','chamber':chamber,'code':code,'boundary_session':2024},'map_session':2026,
            'issue_id':'custom','service_area_id':None,'steps':[{'step_id':'s1','operation':'compare','args':{'metric_ids':[metric],'comparison_geography':comparator}}]}
    def selected(self,request,count=1):
        c=request['context'];r={'schema_version':'haic-investigation/1','request_id':str(uuid.uuid4()),
            **{k:c[k]for k in ('case_id','branch_id','revision','snapshot_id','operation_version','recipe_version')},
            'mode':'run','plan':c['confirmed_plan'],'selected_claim_refs':[],'selected_action_ref':None}
        result=self.i.handle(r);c['selected_claim_refs']=[x['claim_ref']for x in result['claims'][:count]]
        return request
    def test_confirmed_only_rederive_no_candidate_execution(self):
        r=self.request(plan=self.plan());r['context']['draft_plan']=self.plan('senate','025')
        with patch.object(self.i,'handle',wraps=self.i.handle) as handle:
            p=prepare_request(r,self.i,'session')
            self.assertEqual(handle.call_count,1);self.assertEqual(handle.call_args.args[0]['plan'],r['context']['confirmed_plan'])
        r2=self.request('Compare senior poverty with the State.',self.plan());r2['context']['draft_plan']=self.plan('senate','025')
        p2=prepare_request(r2,self.i,'session')  # Confirmed-only re-derivation happens here, before the no-dispatch patch.
        with patch.object(self.i.core,'compare',side_effect=AssertionError('candidate Core dispatch')):
            # The utterance names House28: that resolves the district-only conflict (N4), so the draft's Senate 25 is refused.
            d=self.decision(p,self.plan('senate','025'))
            with self.assertRaises(LanguageError) as c:convert_decision(p,d,self.i.core)
            self.assertEqual(c.exception.code,'explicit_district_conflict')
            # With no district stated the divergent draft still needs the typed control choice, never a proposal.
            out=convert_decision(p2,self.decision(p2,self.plan('senate','025')),self.i.core)
            self.assertEqual((out['status'],out['clarify_field'],out['normalized_plan']),('clarify','control_conflict',None))
            self.assertEqual([c['alias'] for c in out['choices']],['x_confirmed','x_draft'])
    def test_unsupported_confirmed_context_rejected_without_selections(self):
        plan=self.plan(comparator='HI-COUNTY-999-2024')
        with self.assertRaises(LanguageError):prepare_request(self.request(plan=plan),self.i,'session')
        # A draft remains nonexecuting context. It is never re-derived here.
        r=self.request();r['context']['draft_plan']=plan
        with patch.object(self.i,'handle',side_effect=AssertionError('draft dispatch')):prepare_request(r,self.i,'session')
    def test_selection_membership_checked_then_value_free(self):
        r=self.selected(self.request('Why that figure?',self.plan()));p=prepare_request(r,self.i,'session')
        data=dumps(p['provider_context']).decode()
        for private in ('case_id','branch_id','request_id','semantic_hash','snapshot_id','claim_ref','estimate','note','tracking','source_records','sha256:'):
            self.assertNotIn('"'+private+'"',data)
        for v in (r['request_id'],r['context']['case_id'],r['context']['selected_claim_refs'][0]['semantic_hash']):self.assertNotIn(v,data)
        self.assertEqual(list(p['provider_context']['selected']),['selected_1'])
        r['context']['selected_claim_refs'][0]['semantic_hash']='sha256:'+'0'*64
        with self.assertRaises(LanguageError):prepare_request(r,self.i,'session')
    def test_source_is_reference_not_answer(self):
        p=prepare_request(self.selected(self.request('Why that figure?',self.plan())),self.i,'s')
        d=self.decision(p,intent='inspect_source',focus_alias='selected_1');out=convert_decision(p,d,self.i.core)
        self.assertEqual(out['normalized_plan'],None);self.assertTrue(out['source_inspection_refs']);self.assertNotIn('text',out)
        d['answer']='invented'
        with self.assertRaises(LanguageError):convert_decision(p,d,self.i.core)
    def test_distinct_recovery_states_and_closed_shapes(self):
        p=prepare_request(self.request(),self.i,'s')
        for status,reason in [('unsupported','unsupported_operation'),('uncertain','uncertain_interpretation')]:
            d=self.decision(p,status=status,intent='none',reason_code=reason)
            self.assertEqual(convert_decision(p,d,self.i.core)['status'],status)
        d=self.decision(p,status='clarify',intent='none',clarify_field='program',clarify_choices=['p_snap_hi','p_wic_hi'],reason_code='missing_context')
        self.assertEqual(len(convert_decision(p,d,self.i.core)['choices']),2)
        d['clarify_field']='district'
        with self.assertRaises(LanguageError):convert_decision(p,d,self.i.core)
    def test_current_recipes_and_profile_feature_availability(self):
        from districtbrief.interpret import recipe,food_assistance_recipe
        catalog=value_free_catalog(self.i.core);p=prepare_request(self.request('Aging at home in House28.'),self.i,'s')
        district={'state_fips':'15','chamber':'house','code':'028','boundary_session':2024}
        self.assertEqual(convert_decision(p,self.decision(p,recipe(district)),self.i.core)['normalized_plan']['issue_id'],'aging_at_home')
        p=prepare_request(self.request('SNAP outreach in House28.'),self.i,'s');decision=self.decision(p,food_assistance_recipe(district))
        if 'food_assistance_outreach/1' in catalog['recipes']:
            self.assertEqual(convert_decision(p,decision,self.i.core)['normalized_plan']['issue_id'],'food_assistance_outreach')
        else:
            with self.assertRaises(LanguageError):convert_decision(p,decision,self.i.core)
    def test_stable_catalog_digest_excludes_request_specific_aliases(self):
        from districtbrief.claim_binding import digest
        original=value_free_catalog(self.i.core);expected=digest(original)
        for question in ('Profile House28.','Same for Senate25.'):
            p=prepare_request(self.request(question),self.i,'session')
            self.assertEqual(p['catalog_digest'],expected)
            self.assertEqual(digest(value_free_catalog(self.i.core)),expected)
            self.assertNotEqual(digest(p['provider_context']['catalog']),expected)
    def test_step_domain_schema_limits_and_complete_payload(self):
        r=self.request(plan=self.plan());r['context']['confirmed_plan']['steps']=[{'step_id':f's{i}','operation':'profile','args':{'metric_ids':['total_population']}}for i in range(1,9)];r['context']['draft_plan']=copy.deepcopy(r['context']['confirmed_plan'])
        p=prepare_request(r,self.i,'s');stats=lint_schema(p['schema']);self.assertEqual(len(p['step_ids']),16)
        self.assertLess(stats['enum_entries'],1000);self.assertLess(stats['schema_bytes'],32768);self.assertLess(provider_payload(p,PROFILE)[2]['provider_body_bytes'],65536)
        with self.assertRaises(LanguageError):decision_schema(value_free_catalog(self.i.core),[f's{i}'for i in range(1,1000)],p['aliases'],p['choices'])
        d=self.decision(p,self.plan());d['plan']['steps'][0]['step_id']='s999'
        with self.assertRaises(LanguageError):convert_decision(p,d,self.i.core)
    def test_wrong_district_reverse_and_guessed_program_rejected(self):
        plan=self.plan();p=prepare_request(self.request('House28 minus Senate25'),self.i,'s')
        with self.assertRaises(LanguageError):convert_decision(p,self.decision(p,self.plan('senate','025',comparator='HI-HOUSE-028-2024')),self.i.core)
        plan=self.plan();plan['steps']=[{'step_id':'s1','operation':'program_evidence','args':{'program_ids':['snap_hi']}}]
        p=prepare_request(self.request('Food assistance in House28'),self.i,'s')
        out=convert_decision(p,self.decision(p,plan),self.i.core)  # Generic theme: program choices, never SNAP.
        self.assertEqual((out['status'],out['clarify_field'],out['normalized_plan']),('clarify','program',None))
        self.assertEqual([c['value'] for c in out['choices']],['snap_hi','wic_hi'])
    def test_cross_measure_and_unreviewed_outreach_cannot_become_successful_plans(self):
        plan=self.plan();plan['steps']=[{'step_id':'s1','operation':'profile','args':{'metric_ids':['poverty_rate_65_plus','median_household_income']}}]
        # One comparison connector between two measures proves the unsupported request (typed recovery).
        for question in ('Compare senior poverty against median household income in House28.','Compare senior poverty against median income in House28.'):
            p=prepare_request(self.request(question),self.i,'s');out=convert_decision(p,self.decision(p,plan),self.i.core)
            self.assertEqual((out['status'],out['reason_code'],out['normalized_plan']),('unsupported','unsupported_operation',None))
        # Interleaved district/measure pairs are only a heuristic: refused (uncertain), never server-asserted unsupported.
        p=prepare_request(self.request('Compare House28 poverty and Senate25 median household income.'),self.i,'s')
        with self.assertRaises(LanguageError) as c:convert_decision(p,self.decision(p,plan),self.i.core)
        self.assertEqual(c.exception.code,'unsupported_cross_measure')
        plan['steps']=[{'step_id':'s1','operation':'outreach_lead','args':{'program_id':'wic_hi'}}]
        p=prepare_request(self.request('WIC outreach in House28.'),self.i,'s')
        with self.assertRaises(LanguageError):convert_decision(p,self.decision(p,plan),self.i.core)
    def test_explicit_replacement_target_preserves_direction_and_checks_old_context(self):
        prior=self.plan(code='035');prior['map_session']=2024
        proposed=copy.deepcopy(prior);proposed['district'].update(chamber='senate',code='018')
        p=prepare_request(self.request('Retain current steps and the 2024 map, but replace House 35 with Senate 18.',prior),self.i,'s')
        out=convert_decision(p,self.decision(p,proposed),self.i.core)
        self.assertEqual(out['normalized_plan'],proposed)
        for wrong in (prior,self.plan('house','018'),self.plan('senate','035')):
            with self.assertRaises(LanguageError):convert_decision(p,self.decision(p,wrong),self.i.core)
        p=prepare_request(self.request('Replace House 34 with Senate 18.',prior),self.i,'s')
        with self.assertRaises(LanguageError):convert_decision(p,self.decision(p,proposed),self.i.core)
    def test_all_selected_ordinals_and_ambiguous_source_choices(self):
        prior=self.plan();prior['steps']=[{'step_id':f's{n+1}','operation':'profile','args':{'metric_ids':[metric]}}for n,metric in enumerate(list(self.i.core.metrics)[:8])]
        for n,ordinal in enumerate(('first','second','third','fourth','fifth','sixth','seventh','eighth'),1):
            r=self.selected(self.request(f'Inspect only the {ordinal} selected finding source. Keep the investigation unchanged.',prior),8)
            p=prepare_request(r,self.i,'s');d=self.decision(p,intent='inspect_source',focus_alias=f'selected_{n}')
            self.assertEqual(convert_decision(p,d,self.i.core)['source_inspection_refs'],p['aliases'][f'selected_{n}'])
            d['focus_alias']='selected_1'if n!=1 else'selected_2'
            with self.assertRaises(LanguageError):convert_decision(p,d,self.i.core)
        p=prepare_request(self.selected(self.request('Show the selected source.',prior),8),self.i,'s')
        d=self.decision(p,status='clarify',intent='none',clarify_field='referent',clarify_choices=['r_selected_1','r_selected_2'],reason_code='ambiguous_reference')
        self.assertEqual(convert_decision(p,d,self.i.core)['status'],'clarify')
        out=convert_decision(p,self.decision(p,intent='inspect_source',focus_alias='selected_4'),self.i.core)
        self.assertEqual((out['status'],out['clarify_field'],out['source_inspection_refs']),('clarify','referent',[]))
        self.assertEqual([c['alias'] for c in out['choices']],[f'r_selected_{n}' for n in range(1,9)])
    def test_integral_map_representation_and_null_forms(self):
        p=prepare_request(self.request('Make one total-housing-units profile for Senate district 16.'),self.i,'s')
        plan=self.plan('senate','016');plan['steps']=[{'step_id':'s1','operation':'profile','args':{'metric_ids':['total_housing_units']}}]
        d=self.decision(p,plan);d['plan']['map_session']=2026.0
        out=convert_decision(p,d,self.i.core);self.assertEqual(out['normalized_plan'],plan);self.assertIs(type(out['normalized_plan']['map_session']),int)
        for bad in (None,True,2026.5,'2026'):
            wrong=copy.deepcopy(d);wrong['plan']['map_session']=bad
            with self.assertRaises(LanguageError):convert_decision(p,wrong,self.i.core)
        for field in ('focus_alias','clarify_field'):
            wrong=copy.deepcopy(d);wrong[field]=None
            with self.assertRaises(LanguageError):convert_decision(p,wrong,self.i.core)
    def test_diff_includes_removals_changes_and_unchanged_ids(self):
        old=self.plan();old['steps'].append({'step_id':'s2','operation':'profile','args':{'metric_ids':['median_age']}})
        p=prepare_request(self.request('Replace the plan with median age in House28.',old),self.i,'s')
        new=self.plan(metric='median_age');out=convert_decision(p,self.decision(p,new),self.i.core)
        self.assertEqual([x['change'] for x in out['typed_diff'] if x['field']=='steps'],['changed','removed'])
        new=copy.deepcopy(old);new['steps'][0]['step_id']='s3'
        with self.assertRaises(LanguageError):convert_decision(p,self.decision(p,new),self.i.core)
    def test_strict_json_duplicate_nonfinite_and_url_input(self):
        for raw in ('{"a":1,"a":2}','{"a":NaN}','{"a":1e9999}'):
            with self.assertRaises(ValueError):strict_json(raw)
        r=self.request('Read https://example.test')
        with self.assertRaises(LanguageError):prepare_request(r,self.i,'s')
    def test_eighty_development_cases(self):
        cases=json.loads((Path(__file__).parent/'fixtures/ia-language-dev.json').read_text())
        self.assertEqual(len(cases),80)
        for case in cases:
            with self.subTest(case=case['id']):
                plan=self.plan(**case.get('prior',{})) if case.get('prior') is not None else None
                r=self.request(case['utterance'],plan)
                if case.get('selection_count'):r=self.selected(r,case['selection_count'])
                if case.get('failure')=='unknown_field':r['notes']='private'
                if case.get('failure')=='stale_snapshot':r['context']['snapshot_id']='sha256:'+'0'*64
                if case.get('failure')=='invalid_uuid':r['request_id']='bad'
                if case.get('failure')=='oversize':r['utterance']='x'*501
                if case.get('failure'):
                    with self.assertRaises(LanguageError):prepare_request(r,self.i,'dev')
                    continue
                p=prepare_request(r,self.i,'dev')
                target=self.plan(**case.get('target',{})) if case['status']=='propose' and case.get('intent')!='inspect_source' else None
                kwargs={k:case[k]for k in ('status','intent','focus_alias','clarify_field','clarify_choices','reason_code','inherited_fields')if k in case}
                d=self.decision(p,target,**kwargs)
                out=convert_decision(p,d,self.i.core);self.assertEqual(out['status'],case['status'])
                if target:self.assertEqual(out['normalized_plan'],target)

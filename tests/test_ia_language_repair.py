"""Language repair regressions: direction (F1), non-legislative districts (F2), map/service-area grounding,
typed recoveries, terminal mapping and private rejection-stage diagnostics. Injected strict-function wire only."""
import copy
import json
import tempfile
import unittest
import uuid
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.interpret import recipe
from districtbrief.ia_language import EMPTY_PLAN,SCHEMA_VERSION,LanguageError,convert_decision,prepare_request,wire_plan
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import OpenAIProvider
from test_ia_language_accounting import ledger_fixture,usage

def H(code,chamber='house'):return {'state_fips':'15','chamber':chamber,'code':code,'boundary_session':2024}
def plan(district=None,steps=None,map_session=2026,svc=None,issue='custom'):
    return {'district':district or H('028'),'map_session':map_session,'issue_id':issue,'service_area_id':svc,
            'steps':steps or [{'step_id':'s1','operation':'profile','args':{'metric_ids':['median_age']}}]}
def compare(metric,geo,sid='s1'):return {'step_id':sid,'operation':'compare','args':{'metric_ids':[metric],'comparison_geography':geo}}
def profile(metrics,sid='s1'):return {'step_id':sid,'operation':'profile','args':{'metric_ids':metrics}}
def wire(p,map_session=0):
    w=wire_plan(p);w['map_session']=map_session;return w
def decision(status='propose',intent='create_plan',p=None,**kw):
    d={'status':status,'intent':intent,'plan':copy.deepcopy(p) if p is not None else copy.deepcopy(EMPTY_PLAN),'focus_alias':'',
       'clarify_field':'','clarify_choices':[],'reason_code':'','inherited_fields':[]};d.update(kw);return d

class LanguageRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    def request(self,text,confirmed=None,draft='same',selections=0):
        draft=copy.deepcopy(confirmed) if draft=='same' else copy.deepcopy(draft);held=confirmed or draft
        r={'schema_version':SCHEMA_VERSION,'request_id':str(uuid.uuid4()),'utterance':text,'context':{
            'case_id':str(uuid.uuid4()),'branch_id':str(uuid.uuid4()),'revision':1,'snapshot_id':self.i.snapshot_id,
            'operation_version':'ia-core/1','recipe_version':(held['issue_id'] if held else 'custom')+'/1',
            'confirmed_plan':copy.deepcopy(confirmed),'draft_plan':draft,'focused_step_id':None,'selected_claim_refs':[]}}
        if selections:
            c=r['context'];run={'schema_version':'haic-investigation/1','request_id':str(uuid.uuid4()),
                **{k:c[k] for k in ('case_id','branch_id','revision','snapshot_id','operation_version','recipe_version')},
                'mode':'run','plan':c['confirmed_plan'],'selected_claim_refs':[],'selected_action_ref':None}
            c['selected_claim_refs']=[x['claim_ref'] for x in self.i.handle(run)['claims'][:selections]]
        return r
    def convert(self,text,d,confirmed=None,draft='same',selections=0):
        p=prepare_request(self.request(text,confirmed,draft,selections),self.i,'s');return convert_decision(p,d,self.i.core)
    def refused(self,code,*a,**kw):
        with self.assertRaises(LanguageError) as c:self.convert(*a,**kw)
        self.assertEqual(c.exception.code,code)
    def recovered(self,state,*a,field='',reason=None,**kw):
        out=self.convert(*a,**kw)
        self.assertEqual((out['status'],out['intent'],out['normalized_plan'],out['typed_diff'],out['clarify_field']),(state,'none',None,[],field))
        if reason:self.assertEqual(out['reason_code'],reason)
        return out

    # ---- F1: comparator-first wording never certifies a reversed plan
    def test_comparator_first_direction_accepts_correct_and_refuses_reversed(self):
        natural=wire(plan(H('028'),[compare('median_age','HI-SENATE-025-2024')]))
        reversed_=wire(plan(H('025','senate'),[compare('median_age','HI-HOUSE-028-2024')]))
        for text in ('Relative to Senate 25, how does House 28 compare on median age?',
                     'Compared with Senate 25, how does House 28 compare on median age?',
                     'Against Senate 25, compare median age in House 28.',
                     'Using Senate 25 as the baseline, compare median age in House 28.',
                     'Versus SD 25, where does HD 28 stand on median age?',
                     'Compare median age in House 28 against Senate 25.',
                     'Median age: House 28 minus Senate 25.',
                     'Is House 28 older than Senate 25 by median age?'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,decision(p=natural))['normalized_plan']['district'],H('028'))
                self.refused('explicit_district_conflict',text,decision(p=reversed_))
        # The explicit reverse direction is honored, not normalized to the first mention.
        out=self.convert('Senate 25 minus House 28 on median age.',decision(p=reversed_))
        self.assertEqual(out['normalized_plan']['district'],H('025','senate'))
        # Comparator cues on both districts cannot determine a primary: fail closed for either order.
        for d in (natural,reversed_):self.refused('explicit_district_ambiguous','Against House 28 versus Senate 25, compare median age.',decision(p=d))
        # Directed replacement is unchanged.
        prior=plan(H('028'),[compare('median_age','HI-STATE-2024')]);moved=copy.deepcopy(prior);moved['district']=H('025','senate')
        self.assertEqual(self.convert('Replace House 28 with Senate 25.',decision(intent='replace_plan',p=wire(moved)),prior)['normalized_plan']['district'],H('025','senate'))

    # ---- F2: non-legislative district numbers never borrow a held chamber
    def test_nonlegislative_district_is_unsupported_not_a_state_house_district(self):
        held=plan()
        for text in ('Profile median age for congressional district 1.','Profile median age for council district 5.',
                     'Profile median age for Honolulu County Council district 4.','Profile median age for school district 3.',
                     'Profile median age for the U.S. House district 1.','Profile median age for Hawaii congressional district 2.'):
            for proposal,ctx in ((plan(H('001')),held),(plan(H('005')),held),(plan(),held),(plan(H('001')),None)):
                with self.subTest(text=text):
                    self.recovered('unsupported',text,decision(intent='replace_plan' if ctx else 'create_plan',p=wire(proposal)),ctx,reason='unavailable_evidence')
            self.assertEqual(self.convert(text,decision('unsupported','none',reason_code='unavailable_evidence'),held)['status'],'unsupported')
        # Valid State legislative mentions and abbreviations stay proposals.
        for text,code,chamber in (('Profile median age for district 5.','005','house'),('Profile median age for HD 5.','005','house'),
                                  ('Profile median age for SD 5.','005','senate'),('Profile median age for State House district 5.','005','house'),
                                  ('Profile median age for state senate district 5.','005','senate')):
            out=self.convert(text,decision(intent='replace_plan',p=wire(plan(H(code,chamber)))),held)
            self.assertEqual(out['normalized_plan']['district'],H(code,chamber))

    # ---- Map session: explicit > held > default; an unstated model year is refused, never accepted
    def test_unstated_model_map_year_never_replaces_held_or_default_map(self):
        p12=plan(H('012'),[compare('median_age','HI-STATE-2024')])
        for text in ('Compare median age in House 12 with the State.','Compare 2024 median age in House 12 with the State using ACS 2020-2024.'):
            self.assertEqual(self.convert(text,decision(p=wire(p12,0)))['normalized_plan']['map_session'],2026)
            self.assertEqual(self.convert(text,decision(p=wire(p12,2026)))['normalized_plan']['map_session'],2026)
            self.refused('explicit_map_unstated_change',text,decision(p=wire(p12,2024)))
        held=plan(H('028'),[compare('median_age','HI-STATE-2024')],map_session=2024);moved=copy.deepcopy(held);moved['district']=H('025','senate')
        for wire_map in (0,2024):
            out=self.convert('Same for Senate 25.',decision(intent='replace_plan',p=wire(moved,wire_map)),held)
            self.assertEqual(out['normalized_plan']['map_session'],2024);self.assertIn('map_session',out['inherited_fields'])
        self.refused('explicit_map_unstated_change','Same for Senate 25.',decision(intent='replace_plan',p=wire(moved,2026)),held)
        # Explicit selection and exclusion still decide the year.
        out=self.convert('Same for Senate 25 on the 2026 map.',decision(intent='replace_plan',p=wire(moved,2026)),held)
        self.assertEqual(out['normalized_plan']['map_session'],2026);self.assertNotIn('map_session',out['inherited_fields'])
        self.assertEqual(self.convert('Same for Senate 25, not on the 2024 map.',decision(intent='replace_plan',p=wire(moved,2026)),held)['normalized_plan']['map_session'],2026)
        # Held rule (OX-L5): with only an unsaved draft, map 0 or the draft year keeps the draft map; never the default.
        draft=plan(H('012'),[compare('median_age','HI-STATE-2024')],map_session=2024)
        for wire_map in (0,2024):
            self.assertEqual(self.convert('Compare median age in House 12 with the State.',decision(intent='replace_plan',p=wire(draft,wire_map)),None,draft)['normalized_plan']['map_session'],2024)
        self.refused('explicit_map_unstated_change','Compare median age in House 12 with the State.',decision(intent='replace_plan',p=wire(draft,2026)),None,draft)

    # ---- Service area is a staff scope: never silently dropped or invented
    def test_service_area_is_kept_named_or_explicitly_removed(self):
        held=plan(H('028'),[compare('median_age','HI-STATE-2024')],svc='oahu');moved=copy.deepcopy(held);moved['district']=H('025','senate')
        out=self.convert('Same for Senate 25.',decision(intent='replace_plan',p=wire(moved)),held)
        self.assertEqual(out['normalized_plan']['service_area_id'],'oahu');self.assertIn('service_area_id',out['inherited_fields'])
        self.refused('explicit_service_area_unstated_change','Same for Senate 25.',decision(intent='replace_plan',p=wire(dict(moved,service_area_id=None))),held)
        self.refused('explicit_service_area_unstated','Same for Senate 25.',decision(intent='replace_plan',p=wire(dict(moved,service_area_id='maui'))),held)
        out=self.convert('Same for Senate 25 but use the Maui service area.',decision(intent='replace_plan',p=wire(dict(moved,service_area_id='maui'))),held)
        self.assertEqual(out['normalized_plan']['service_area_id'],'maui')
        self.assertEqual(self.convert('Same for Senate 25 with the Kauaʻi service area.',decision(intent='replace_plan',p=wire(dict(moved,service_area_id='kauai'))),held)['normalized_plan']['service_area_id'],'kauai')
        out=self.convert('Same for Senate 25 without a service area.',decision(intent='replace_plan',p=wire(dict(moved,service_area_id=None))),held)
        self.assertIsNone(out['normalized_plan']['service_area_id'])
        self.refused('explicit_service_area_unstated','Compare median age in House 12 with the State.',decision(p=wire(plan(H('012'),[compare('median_age','HI-STATE-2024')],svc='oahu'))))

    # ---- A named measure is not broadened to an all-measures profile
    def test_named_measure_profile_is_not_broadened(self):
        self.assertEqual(self.convert('Profile median household income for House 7.',decision(p=wire(plan(H('007'),[profile(['median_household_income'])]))))['normalized_plan']['steps'][0]['args'],{'metric_ids':['median_household_income']})
        self.refused('explicit_metric_conflict','Profile median household income for House 7.',decision(p=wire(plan(H('007'),[profile([])]))))
        out=self.convert('Give me a full profile for House 7, including median household income.',decision(p=wire(plan(H('007'),[profile([])]))))
        self.assertIsNone(out['normalized_plan']['steps'][0]['args']['metric_ids'])
        self.assertIsNone(self.convert('Profile House 7.',decision(p=wire(plan(H('007'),[profile([])]))))['normalized_plan']['steps'][0]['args']['metric_ids'])

    # ---- Inherited labels list exactly the retained confirmed fields
    def test_inherited_labels_are_exact_retained_confirmed_fields(self):
        held=plan(H('028'),[compare('poverty_rate_65_plus','HI-STATE-2024')]);moved=copy.deepcopy(held);moved['district']=H('025','senate')
        for text in ('Same for Senate 25.','Run the same senior poverty comparison for Senate 25.'):
            out=self.convert(text,decision(intent='replace_plan',p=wire(moved)),held)
            self.assertEqual(out['inherited_fields'],['map_session','issue_id','service_area_id','steps'],text)
        # An exact restatement of the same value is stated, not inherited (OX-L11 truthful label).
        out=self.convert('Keep the 2026 map and switch the district to Senate 25.',decision(intent='replace_plan',p=wire(moved,2026)),held)
        self.assertEqual(out['inherited_fields'],['issue_id','service_area_id','steps'])
        out=self.convert('Compare senior poverty in House 28 with the State.',decision(intent='replace_plan',p=wire(held)),held)
        self.assertNotIn('district',out['inherited_fields']);self.assertIn('steps',out['inherited_fields'])
        added=copy.deepcopy(held);added['steps'].append(profile(['median_age'],'s2'))
        out=self.convert('Also add a median age profile.',decision(intent='replace_plan',p=wire(added)),held)
        self.assertEqual(out['inherited_fields'],['district','map_session','issue_id','service_area_id'])
        self.assertEqual(self.convert('Compare senior poverty in House 28 with the State.',decision(p=wire(held)),None,held)['inherited_fields'],[])  # draft is not confirmed

    # ---- Typed recoveries replace refused proposals; model-authored shapes stay strict
    def test_typed_recoveries_render_fixed_choices_and_never_a_plan(self):
        snap=wire(plan(H('028'),[{'step_id':'s1','operation':'program_evidence','args':{'program_ids':['snap_hi']}}]))
        out=self.recovered('clarify','Show food assistance evidence for House 28.',decision(p=snap),field='program',reason='missing_context')
        self.assertEqual([c['alias'] for c in out['choices']],['p_snap_hi','p_wic_hi'])
        out=self.recovered('clarify','Which housing assistance applies in House 28?',decision(p=snap),field='program')
        self.assertEqual([c['value'] for c in out['choices']],['hcv_honolulu'])
        # A named program is grounded: no recovery.
        self.assertEqual(self.convert('Show SNAP food assistance evidence for House 28.',decision(p=snap))['status'],'propose')
        out=self.recovered('clarify','Compare poverty in House 28 with the State.',decision(p=wire(plan(H('028'),[compare('poverty_rate_all_people','HI-STATE-2024')]))),field='metric')
        self.assertEqual([c['value'] for c in out['choices']],['poverty_rate_all_people','poverty_rate_65_plus'])
        for text in ('Which residents in House 28 qualify for SNAP?','What caused poverty in House 28?','Forecast unemployment in House 28.',
                     'Compare poverty against median income in House 28.'):
            self.recovered('unsupported',text,decision(p=snap),reason='unsupported_operation')
        conf=plan();draft=plan(steps=[profile(['median_household_income'])])
        out=self.recovered('clarify','Compare it with the State.',decision(intent='replace_plan',p=wire(plan(steps=[compare('median_age','HI-STATE-2024')]))),conf,draft,field='control_conflict')
        self.assertEqual([c['alias'] for c in out['choices']],['x_confirmed','x_draft'])
        out=self.recovered('clarify','Why that figure?',decision(intent='inspect_source',focus_alias='selected_1'),recipe(H('028')),selections=2,field='referent',reason='ambiguous_reference')
        self.assertEqual([c['alias'] for c in out['choices']],['r_selected_1','r_selected_2'])
        # A recovery takes precedence over an unrelated model map error, but not over a model's own nonproposal shape.
        self.recovered('clarify','Show food assistance evidence for House 28.',decision(p=dict(snap,map_session=2024)),field='program')
        bad=decision('clarify','none',p={**EMPTY_PLAN,'district':{'chamber':'house','code':'028'}},clarify_field='program',clarify_choices=['p_snap_hi'],reason_code='missing_context')
        self.refused('inapplicable_provider_fields','Show food assistance evidence for House 28.',bad)
        # A model's own well-formed clarification is unchanged.
        own=decision('clarify','none',clarify_field='district',clarify_choices=['d_h001','d_s001'],reason_code='missing_context')
        self.assertEqual([c['alias'] for c in self.convert('Profile district 1.',own)['choices']],['d_h001','d_s001'])

class LanguageRepairJobTests(unittest.TestCase):
    """Actual adapter/job path with a completed strict function-call body (reasoning item + one function_call)."""
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ledger=ledger_fixture(self.tmp.name);self.bodies=[]
        def transport(method,path,body,secret,deadline):
            if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':1000}
            return 200,self.bodies.pop(0)
        self.provider=OpenAIProvider(transport=transport,secret_reader=lambda:'injected-no-network')
        self.service=LanguageService(self.i,enabled=True,ledger=self.ledger,provider=self.provider)
    def tearDown(self):
        self.service.close()
        if self.service._executor:self.service._executor.shutdown(wait=True)
        self.tmp.cleanup()
    def body(self,arguments,**top):
        b={'id':'resp_injected','object':'response','status':'completed','model':'gpt-6.1-terra','service_tier':'default',
           'reasoning':{'effort':'low','summary':None},'usage':usage(),
           'output':[{'type':'reasoning','id':'rs_injected','summary':[]},
                     {'type':'function_call','id':'fc_injected','call_id':'call_injected','name':'ia_language_decision',
                      'status':'completed','arguments':arguments if isinstance(arguments,str) else json.dumps(arguments)}]}
        b.update(top);return b
    def run_job(self,text,arguments,confirmed=None,draft='same',**top):
        # One fresh synthetic ledger per job: the fixture count ceiling is not under test here.
        self.service.close();tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.ledger=ledger_fixture(tmp.name)
        self.service=LanguageService(self.i,enabled=True,ledger=self.ledger,provider=self.provider)
        r=LanguageRepairTests.request(self,text,confirmed,draft);self.bodies.append(self.body(arguments,**top));events=[]
        code,out=self.service.operator_start(r,diagnostic_sink=events.append);self.assertEqual(code,202,out)
        code,out=self.service.operator_wait(r['request_id']);self.assertEqual(code,200)
        summary=self.ledger.summary();self.assertEqual(summary['buckets']['test']['entries'],1);self.assertFalse(summary['unresolved'])
        return out,{e['event']:e for e in events}

    def test_recovery_through_job_is_typed_and_private_stage_is_recorded_after_settlement(self):
        snap=wire(plan(H('028'),[{'step_id':'s1','operation':'program_evidence','args':{'program_ids':['snap_hi']}}]))
        out,ev=self.run_job('Show food assistance evidence for House 28.',decision(p=snap))
        self.assertEqual((out['status'],out['clarify_field'],out['model_calls']),('clarify','program',1))
        self.assertNotIn('recovered_from',out);self.assertNotIn('stage',json.dumps(out));self.assertNotIn('function_arguments',out)
        self.assertEqual(ev['provider_result']['settlement'],'known_usage_settled')
        self.assertEqual((ev['local_result']['status'],ev['local_result']['recovered_from'],ev['local_result']['rejection_code']),('clarify','ungrounded_program',None))

    def test_each_rejection_layer_is_named_and_model_content_refusals_are_uncertain(self):
        held=plan();moved=copy.deepcopy(held);moved['district']=H('025','senate')
        cases=[('wire_schema','invalid_provider_enum','Profile House 28.',dict(decision(p=wire(plan())),status='answer'),None),
               ('decision_fields','inapplicable_provider_fields','Profile House 28.',decision(p=wire(plan()),reason_code='missing_context'),None),
               ('map_session','explicit_map_unstated_change','Profile median age in House 28.',decision(p=wire(plan(),2024)),None),
               ('plan_conversion','inapplicable_provider_fields','Profile median age in House 28.',decision(p=dict(wire(plan()),steps=[dict(wire(plan())['steps'][0],program_ids=['snap_hi'])])),None),
               ('local_guard','explicit_district_conflict','Profile median age in House 28.',decision(p=wire(plan(H('029')))),None),
               ('inheritance','invalid_inheritance','Same for Senate 25.',decision(intent='replace_plan',p=wire(moved),inherited_fields=['district']),held),
               ('source_reference','inapplicable_provider_fields','Why that figure?',decision(intent='inspect_source',focus_alias='source_1',inherited_fields=['focus']),None),
               ('nonproposal_fields','invalid_unsupported_reason','Forecast House 28.',decision('unsupported','none'),None),
               ('nonproposal_fields','invalid_clarification','Profile poverty in House 28.',decision('clarify','none',clarify_field='metric',clarify_choices=['c_house'],reason_code='missing_context'),None),
               ('nonproposal_fields','inapplicable_provider_fields','Forecast House 28.',decision('unsupported','none',p={**EMPTY_PLAN,'map_session':2026},reason_code='unsupported_operation'),None)]
        for stage,code,text,d,confirmed in cases:
            with self.subTest(stage=stage,code=code):
                out,ev=self.run_job(text,d,confirmed)
                self.assertEqual((out['status'],out['reason_code'],out['model_calls']),('uncertain','uncertain_interpretation',1))
                self.assertEqual((ev['local_result']['stage'],ev['local_result']['rejection_code']),(stage,code))
                self.assertEqual(ev['provider_result']['settlement'],'known_usage_settled')
        out,ev=self.run_job('Profile House 28.','{"status":"propose"')  # truncated strict arguments
        self.assertEqual((out['status'],ev['local_result']['stage'],ev['local_result']['rejection_code']),('uncertain','provider','invalid_provider_arguments'))
        out,ev=self.run_job('Profile House 28.',decision(p=wire(plan())),status='incomplete')
        self.assertEqual((out['status'],ev['local_result']['stage'],ev['local_result']['rejection_code']),('error','provider','provider_incomplete'))

if __name__=='__main__':unittest.main()

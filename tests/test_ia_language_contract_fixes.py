"""Contract-level guard fixes, synthetic wording only (no held-out, replay or provider content):
D1 a program theme clarifies only when the proposal selects an unnamed, uninherited program;
D2 a bare causal/eligibility/non-legislative keyword is uncertain, an explicit request stays unsupported;
D3 a measure that singles out one selected claim resolves the referent, several viable ones still clarify;
D4 an explicit map year beside the not-stated sentinel is refused, never server-filled as a model decision.
Injected strict-function wire only; a recovery never carries a plan, diff, source or fact."""
import copy
import json
import tempfile
import unittest
import uuid
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.ia_language import EMPTY_PLAN,SCHEMA_VERSION,LanguageError,convert_decision,prepare_request,wire_plan
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import OpenAIProvider
from test_ia_language_accounting import ledger_fixture,usage

S='HI-STATE-2024'
def H(code,chamber='house'):return {'state_fips':'15','chamber':chamber,'code':code,'boundary_session':2024}
def plan(steps,district=None,map_session=2026):
    return {'district':district or H('028'),'map_session':map_session,'issue_id':'custom','service_area_id':None,'steps':steps}
def profile(metrics,sid='s1'):return {'step_id':sid,'operation':'profile','args':{'metric_ids':metrics}}
def compare(metric,geo=S,sid='s1'):return {'step_id':sid,'operation':'compare','args':{'metric_ids':[metric],'comparison_geography':geo}}
def evidence(programs,sid='s1'):return {'step_id':sid,'operation':'program_evidence','args':{'program_ids':programs}}
def wire(p,map_session=0):
    w=wire_plan(p);w['map_session']=map_session;return w
def decision(status='propose',intent='create_plan',p=None,**kw):
    d={'status':status,'intent':intent,'plan':copy.deepcopy(p) if p is not None else copy.deepcopy(EMPTY_PLAN),'focus_alias':'',
       'clarify_field':'','clarify_choices':[],'reason_code':'','inherited_fields':[]};d.update(kw);return d
AGE=plan([profile(['median_age'])])
SNAP=plan([evidence(['snap_hi'])])
# Claim order of this confirmed plan (deterministic): 0 median_age, 1 median_household_income,
# 2 poverty_rate_all_people, 3 poverty_rate_65_plus, 4 median_age (compare step), 5 median_age comparison.
MIXED=plan([profile(['median_age','poverty_rate_65_plus','poverty_rate_all_people','median_household_income']),compare('median_age',sid='s2')])
SELECTED_KEYS={'kind','step_id','metric_id','program_id','geography','period','source_ids'}

class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    def request(self,text,confirmed=None,draft='same',picks=()):
        draft=copy.deepcopy(confirmed) if draft=='same' else copy.deepcopy(draft)
        r={'schema_version':SCHEMA_VERSION,'request_id':str(uuid.uuid4()),'utterance':text,'context':{
            'case_id':str(uuid.uuid4()),'branch_id':str(uuid.uuid4()),'revision':1,'snapshot_id':self.i.snapshot_id,
            'operation_version':'ia-core/1','recipe_version':'custom/1',
            'confirmed_plan':copy.deepcopy(confirmed),'draft_plan':draft,'focused_step_id':None,'selected_claim_refs':[]}}
        if picks:
            c=r['context'];run={'schema_version':'haic-investigation/1','request_id':str(uuid.uuid4()),
                **{k:c[k] for k in ('case_id','branch_id','revision','snapshot_id','operation_version','recipe_version')},
                'mode':'run','plan':c['confirmed_plan'],'selected_claim_refs':[],'selected_action_ref':None}
            claims=self.i.handle(run)['claims'];c['selected_claim_refs']=[claims[n]['claim_ref'] for n in picks]
        return r
    def prepared(self,*a,**kw):return prepare_request(self.request(*a,**kw),self.i,'s')
    def convert(self,text,d,confirmed=None,draft='same',picks=()):
        self.last=self.prepared(text,confirmed,draft,picks);return convert_decision(self.last,d,self.i.core)
    def refused(self,code,*a,**kw):
        with self.assertRaises(LanguageError) as c:self.convert(*a,**kw)
        self.assertEqual(c.exception.code,code)
    def recovered(self,state,*a,field='',reason=None,**kw):
        out=self.convert(*a,**kw)
        # No fact/Plan generation in a recovery: fixed template, no plan, diff, source or inherited label.
        self.assertEqual((out['status'],out['intent'],out['normalized_plan'],out['typed_diff'],out['source_inspection_refs'],out['inherited_fields'],out['clarify_field']),
                         (state,'none',None,[],[],[],field))
        for choice in out['choices']:self.assertEqual(choice,self.last['choices'][choice['alias']])
        if reason:self.assertEqual(out['reason_code'],reason)
        return out

class ProgramThemeTests(Base):
    def test_theme_without_a_program_step_proposes(self):
        for text in ('Profile median age in House 28 for our food assistance briefing.',
                     'Profile median age in House 28 ahead of the housing assistance hearing.',
                     'Profile median age in House 28 for the benefits program working group.'):
            out=self.convert(text,decision(p=wire(AGE)))
            self.assertEqual((out['status'],out['normalized_plan']),('propose',AGE),text)
    def test_theme_with_only_a_confirmed_program_retained_proposes(self):
        added=copy.deepcopy(SNAP);added['steps'].append(profile(['median_age'],'s2'))
        out=self.convert('Also add a median age profile for the nutrition program briefing.',decision(intent='replace_plan',p=wire(added)),SNAP)
        self.assertEqual((out['status'],out['normalized_plan']['steps']),('propose',added['steps']))
    def test_theme_selecting_an_unnamed_program_still_clarifies(self):
        out=self.recovered('clarify','Show food assistance evidence for House 28.',decision(p=wire(SNAP)),field='program',reason='missing_context')
        self.assertEqual([c['alias'] for c in out['choices']],['p_snap_hi','p_wic_hi'])
        added=copy.deepcopy(AGE);added['steps'].append(evidence(['wic_hi'],'s2'))
        out=self.recovered('clarify','Also show nutrition program evidence.',decision(intent='replace_plan',p=wire(added)),AGE,field='program')
        self.assertEqual([c['value'] for c in out['choices']],['snap_hi','wic_hi'])
        # A new unnamed program beside a retained confirmed one is still an unnamed selection.
        more=copy.deepcopy(SNAP);more['steps'][0]['args']['program_ids']=['snap_hi','wic_hi']
        self.recovered('clarify','Also include the other food program.',decision(intent='replace_plan',p=wire(more)),SNAP,field='program')
        # A draft-only program is not confirmed context.
        self.recovered('clarify','Show the food assistance evidence.',decision(intent='replace_plan',p=wire(SNAP)),None,SNAP,field='program')
    def test_named_and_unthemed_program_behavior_is_unchanged(self):
        self.assertEqual(self.convert('Show SNAP food assistance evidence for House 28.',decision(p=wire(SNAP)))['status'],'propose')
        self.refused('ungrounded_program','Show program evidence for House 28.',decision(p=wire(SNAP)))
        self.refused('ungrounded_program','Show SNAP food assistance evidence for House 28.',decision(p=wire(plan([evidence(['snap_hi','wic_hi'])]))))

class UnsupportedProofTests(Base):
    def test_bare_keyword_is_uncertain_not_unsupported_and_never_a_plan(self):
        for text,p in (('Show SNAP program evidence for House 28, including its eligibility rules.',SNAP),
                       ('Show SNAP program evidence for House 28 and the eligibility reference.',SNAP),
                       ('Profile median age in House 28; the causal story is a separate memo.',AGE),
                       ('Profile median age in House 28 for the root cause working group.',AGE)):
            self.refused('unsupported_inference_unproven',text,decision(p=wire(p)))
    def test_explicit_unsupported_request_stays_unsupported(self):
        for text in ('Who is eligible for SNAP in House 28?','How many residents of House 28 qualify for SNAP?',
                     'Is a household in House 28 eligible for SNAP?','Estimate SNAP eligibility in House 28.',
                     'Did SNAP cause the drop in senior poverty in House 28?','What is the causal effect of SNAP in House 28?',
                     'Show what poverty in House 28 is caused by.','Forecast SNAP use in House 28.',
                     'Show the SNAP participation gap in House 28.','List the names of residents on SNAP in House 28.'):
            with self.subTest(text=text):self.recovered('unsupported',text,decision(p=wire(SNAP)),reason='unsupported_operation')
        # The model's own unsupported decision is untouched.
        self.assertEqual(self.convert('Who is eligible for SNAP in House 28?',decision('unsupported','none',reason_code='unsupported_operation'))['status'],'unsupported')
    def test_negated_or_benign_wording_proposes(self):
        for text in ('Show SNAP program evidence for House 28; do not determine eligibility.',
                     'Show SNAP program evidence for House 28 with no causal claims.',
                     'Show SNAP program evidence for House 28 for our qualifying grant report.'):
            self.assertEqual(self.convert(text,decision(p=wire(SNAP)))['normalized_plan'],SNAP,text)
    def test_nonlegislative_beside_a_named_state_district_is_uncertain(self):
        for text in ('Profile median age in House 28; it overlaps council district 5.',
                     'Profile median age in HD 28, which sits inside congressional district 1.',
                     'Profile median age in House 28 for the school district 3 liaison.'):
            self.refused('nonlegislative_district_unproven',text,decision(p=wire(AGE)))
    def test_nonlegislative_requested_geography_stays_unsupported(self):
        cmp_=plan([compare('median_age')])
        for text,p,held in (('Profile median age for council district 5.',plan([profile(['median_age'])],H('005')),None),
                            ('Profile median age for congressional district 1.',AGE,AGE),
                            ('Compare median age in House 28 with congressional district 1.',cmp_,None),
                            ('Compare median age in House 28 against the school district 3.',cmp_,None),
                            ('Median age: House 28 versus council district 5.',cmp_,None)):
            with self.subTest(text=text):
                self.recovered('unsupported',text,decision(intent='replace_plan' if held else 'create_plan',p=wire(p)),held,reason='unavailable_evidence')
        self.assertEqual(self.convert('Profile median age in House 28 for my congressional testimony.',decision(p=wire(AGE)))['status'],'propose')

class MeasureReferentTests(Base):
    def inspect(self,text,focus,picks):
        return self.convert(text,decision(intent='inspect_source',focus_alias=focus),MIXED,picks=picks)
    def test_measure_singles_out_one_selected_claim(self):
        for text,focus,picks in (('Why is that median household income figure so low?','selected_2',(0,1)),
                                 ('Where does the median age number come from?','selected_1',(0,1)),
                                 ('What is the source for that poverty figure?','selected_2',(0,2)),  # one poverty claim selected
                                 ('Why that senior poverty figure?','selected_2',(2,3)),
                                 ('Explain the definition of the poverty rate, all people figure.','selected_1',(2,3)),
                                 ('Why that median household income figure?','selected_3',(0,2,1,3))):
            with self.subTest(text=text):
                out=self.inspect(text,focus,picks)
                self.assertEqual((out['status'],out['intent'],out['normalized_plan'],out['choices']),('propose','inspect_source',None,[]))
                self.assertEqual(out['source_inspection_refs'],self.last['aliases'][focus]);self.assertTrue(out['source_inspection_refs'])
    def test_model_focus_on_another_claim_is_refused(self):
        self.refused('ambiguous_reference','Why is that median household income figure so low?',decision(intent='inspect_source',focus_alias='selected_1'),MIXED,picks=(0,1))
        self.refused('ambiguous_reference','Why is that median household income figure so low?',decision(intent='inspect_source',focus_alias='source_1'),MIXED,picks=(0,1))
    def test_several_viable_referents_still_clarify(self):
        for text,picks in (('Why that figure?',(0,1)),                      # no measure named
                           ('Why that poverty figure?',(2,3)),              # generic poverty, both poverty claims
                           ('Why that median age figure?',(0,5)),           # statistic and comparison share the measure
                           ('Why that median age figure?',(0,5,1)),         # two of three selected share the measure
                           ('Why those median age and median household income figures?',(0,1)),
                           ('Why that unemployment rate figure?',(0,1))):   # names no selected measure
            for focus in ('selected_1','selected_2'):
                with self.subTest(text=text,focus=focus):
                    out=self.recovered('clarify',text,decision(intent='inspect_source',focus_alias=focus),MIXED,picks=picks,field='referent',reason='ambiguous_reference')
                    self.assertEqual([c['alias'] for c in out['choices']],[f'r_selected_{n}' for n in range(1,len(picks)+1)])
    def test_explicit_alias_and_single_selection_paths_are_unchanged(self):
        self.assertEqual(self.inspect('Why the second selected figure?','selected_2',(0,1))['status'],'propose')
        self.refused('ambiguous_reference','Why the second selected figure for median age?',decision(intent='inspect_source',focus_alias='selected_1'),MIXED,picks=(0,1))
        self.assertEqual(self.inspect('Why that figure?','selected_1',(1,))['status'],'propose')
    def test_selected_provider_metadata_stays_value_free(self):
        p=self.prepared('Why is that median household income figure so low?',MIXED,picks=(0,1,2,3))
        for row in p['provider_context']['selected'].values():self.assertEqual(set(row),SELECTED_KEYS)
        self.assertEqual(set(p['provider_context']),{'utterance','confirmed_plan','draft_plan','focused_step_id','selected','catalog','step_ids','control_conflict'})

class MapSentinelTests(Base):
    def test_explicit_year_with_sentinel_is_refused_and_reported_year_is_accepted(self):
        for year in (2024,2026):
            for text in (f'Profile median age in House 28 on the {year} map.',f'Profile median age in House 28 using the {year} legislative districts.',
                         f'Profile median age in House 28 for map session {year}.'):
                with self.subTest(text=text):
                    self.refused('explicit_map_unreported',text,decision(p=wire(AGE)))
                    out=self.convert(text,decision(p=wire(AGE,year)))
                    self.assertEqual((out['status'],out['normalized_plan']['map_session']),('propose',year))
                    self.refused('explicit_map_conflict',text,decision(p=wire(AGE,4050-year)))
        held=plan([profile(['median_age'])],map_session=2024)
        text='Switch this plan from the 2024 map to the 2026 map.'
        self.refused('explicit_map_unreported',text,decision(intent='replace_plan',p=wire(held)),held)
        out=self.convert(text,decision(intent='replace_plan',p=wire(held,2026)),held)
        self.assertEqual(out['normalized_plan']['map_session'],2026);self.assertNotIn('map_session',out['inherited_fields'])
        self.assertIn({'field':'map_session','change':'changed','before':2024,'after':2026},out['typed_diff'])
    def test_unstated_map_keeps_held_default_and_inherited_semantics(self):
        self.assertEqual(self.convert('Profile median age in House 28.',decision(p=wire(AGE)))['normalized_plan']['map_session'],2026)
        self.assertEqual(self.convert('Profile median age in House 28 using 2020-2024 ACS data.',decision(p=wire(AGE)))['normalized_plan']['map_session'],2026)
        self.assertEqual(self.convert('Profile median age in House 28, not on the 2024 map.',decision(p=wire(AGE)))['normalized_plan']['map_session'],2026)
        self.refused('explicit_map_unstated_change','Profile median age in House 28.',decision(p=wire(AGE,2024)))
        held=plan([profile(['median_age'])],map_session=2024);added=copy.deepcopy(held);added['steps'].append(profile(['median_household_income'],'s2'))
        out=self.convert('Also add a median household income profile.',decision(intent='replace_plan',p=wire(added)),held)
        self.assertEqual((out['normalized_plan']['map_session'],out['inherited_fields']),(2024,['district','map_session','issue_id','service_area_id']))
        draft_only=self.convert('Also add a median household income profile.',decision(intent='replace_plan',p=wire(added)),None,held)
        self.assertEqual((draft_only['normalized_plan']['map_session'],draft_only['inherited_fields']),(2024,[]))
        # A restated held year is stated, not inherited; it must still be reported by the model.
        self.refused('explicit_map_unreported','Keep the 2024 map and add a median household income profile.',decision(intent='replace_plan',p=wire(added)),held)
        out=self.convert('Keep the 2024 map and add a median household income profile.',decision(intent='replace_plan',p=wire(added,2024)),held)
        self.assertEqual(out['inherited_fields'],['district','issue_id','service_area_id'])

class JobAttributionTests(Base):
    """Actual adapter/job path with an injected completed body: closed attribution for each fixed case."""
    def setUp(self):
        self.bodies=[]
        def transport(method,path,body,secret,deadline):
            if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':1000}
            return 200,self.bodies.pop(0)
        self.provider=OpenAIProvider(transport=transport,secret_reader=lambda:'injected-no-network')
    def run_job(self,text,d,confirmed=None,picks=()):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        service=LanguageService(self.i,enabled=True,ledger=ledger_fixture(tmp.name),provider=self.provider)
        def close():
            service.close()
            if service._executor:service._executor.shutdown(wait=True)
        self.addCleanup(close)
        self.bodies.append({'id':'resp_injected','object':'response','status':'completed','model':'gpt-6.1-terra','service_tier':'default',
            'reasoning':{'effort':'low','summary':None},'usage':usage(),
            'output':[{'type':'reasoning','id':'rs_injected','summary':[]},
                      {'type':'function_call','id':'fc_injected','call_id':'call_injected','name':'ia_language_decision','status':'completed','arguments':json.dumps(d)}]})
        r=self.request(text,confirmed,picks=picks);events=[]
        code,out=service.operator_start(r,diagnostic_sink=events.append);self.assertEqual(code,202,out)
        code,out=service.operator_wait(r['request_id']);self.assertEqual(code,200)
        self.assertEqual(out['model_calls'],1);self.assertNotIn(text,json.dumps(out))
        return out,{e['event']:e for e in events}['local_result']
    def test_terminal_states_and_attribution(self):
        cases=[  # text, decision, confirmed, picks, status, origin, category, private rejection code
            ('Profile median age in House 28 for our food assistance briefing.',decision(p=wire(AGE)),None,(),'propose','model','',None),
            ('Show food assistance evidence for House 28.',decision(p=wire(SNAP)),None,(),'clarify','server_recovery','generic_program_theme',None),
            ('Show SNAP program evidence for House 28, including its eligibility rules.',decision(p=wire(SNAP)),None,(),'uncertain','server_refusal','','unsupported_inference_unproven'),
            ('Who is eligible for SNAP in House 28?',decision(p=wire(SNAP)),None,(),'unsupported','server_recovery','unsupported_inference',None),
            ('Profile median age in House 28; it overlaps council district 5.',decision(p=wire(AGE)),None,(),'uncertain','server_refusal','','nonlegislative_district_unproven'),
            ('Profile median age for council district 5.',decision(p=wire(plan([profile(['median_age'])],H('005')))),None,(),'unsupported','server_recovery','nonlegislative_district',None),
            ('Why is that median household income figure so low?',decision(intent='inspect_source',focus_alias='selected_2'),MIXED,(0,1),'propose','model','',None),
            ('Why that median age figure?',decision(intent='inspect_source',focus_alias='selected_1'),MIXED,(0,5),'clarify','server_recovery','ambiguous_referent',None),
            ('Profile median age in House 28 on the 2024 map.',decision(p=wire(AGE)),None,(),'uncertain','server_refusal','','explicit_map_unreported'),
            ('Profile median age in House 28 on the 2024 map.',decision(p=wire(AGE,2024)),None,(),'propose','model','',None)]
        for text,d,confirmed,picks,status,origin,category,code in cases:
            with self.subTest(text=text,status=status):
                out,local=self.run_job(text,d,confirmed,picks)
                self.assertEqual((out['status'],out['attribution']['decision_origin'],out['attribution']['recovery_category']),(status,origin,category))
                self.assertEqual(local['rejection_code'],code)
                if status!='propose' or d['intent']=='inspect_source':self.assertIsNone(out.get('normalized_plan'))
                if status=='uncertain':
                    self.assertEqual(out['reason_code'],'uncertain_interpretation')
                    self.assertFalse(out.get('choices'));self.assertFalse(out.get('source_inspection_refs'))
                if status=='propose' and d['intent']=='create_plan':self.assertEqual(out['normalized_plan']['map_session'],d['plan']['map_session'] or 2026)

if __name__=='__main__':unittest.main()

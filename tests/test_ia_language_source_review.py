"""OX language source review (v1 -> v2) regressions: held-context direction, metric edits, cross-measure,
held rule, jurisdiction, comparator provenance, service-area scope, transport classification, control conflict,
negated constraints and closed decision attribution. Injected strict-function wire only; no quality claim."""
import os
import time
import copy
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import unittest
import test_ia_language_proposals as proposal_fixtures
import test_ia_language_repair as repair  # module import: its TestCases are not re-collected here
from test_ia_language_repair import H,plan,compare,profile,wire,decision
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.ia_language import LanguageError
from districtbrief.ia_language_jobs import ATTRIBUTION_VALUES

S='HI-STATE-2024'
def pov(geo,sid='s1'):return compare('poverty_rate_65_plus',geo,sid)

class SourceReviewGuardTests(unittest.TestCase):
    # Borrow the repair helpers without re-collecting their tests.
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    request=repair.LanguageRepairTests.request;convert=repair.LanguageRepairTests.convert
    refused=repair.LanguageRepairTests.refused;recovered=repair.LanguageRepairTests.recovered
    def test_held_primary_stays_primary_when_only_a_comparator_is_named(self):
        held=plan(H('028'),[pov(S)])
        correct=decision(intent='replace_plan',p=wire(plan(H('028'),[pov('HI-HOUSE-030-2024')])))
        reversed_=decision(intent='replace_plan',p=wire(plan(H('030'),[pov('HI-HOUSE-028-2024')])))
        for text in ('Compare senior poverty with House 30.','Compare senior poverty to House 30.','Now compare it with House 30 instead of the State.',
                     'Compare senior poverty against House 30.','How does it look relative to House 30?','Compare senior poverty versus HD 30.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,correct,held)['normalized_plan']['district'],H('028'))
                self.refused('explicit_district_conflict',text,reversed_,held)
        # With no held plan the primary is proven missing: typed choices, never a guess (repair-1: chamber asked first).
        self.recovered('clarify','Compare senior poverty with House 30.',decision(p=wire(plan(H('030'),[pov('HI-HOUSE-028-2024')]))),field='chamber')
        # Navigation to a newly named primary (no comparison cue) is not a comparator: the held primary may not
        # silently become the comparator.
        self.refused('explicit_comparator_unstated','Show senior poverty for House 30.',reversed_,held)

    def test_comparator_first_cues_and_unprovable_roles(self):
        nat=decision(p=wire(plan(H('028'),[pov('HI-SENATE-025-2024')])));rev=decision(p=wire(plan(H('025','senate'),[pov('HI-HOUSE-028-2024')])))
        for text in ('Compare with Senate 25: how does House 28 do on senior poverty?','Compare to Senate 25, House 28 senior poverty.',
                     'Senate 25 serves as the comparison for House 28 senior poverty.','Compare House 28 senior poverty to Senate 25.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,nat)['normalized_plan']['district'],H('028'))
                self.refused('explicit_district_conflict',text,rev)
        for d in (nat,rev):self.refused('explicit_district_ambiguous','Against House 28 and versus Senate 25, compare senior poverty.',d)

    def test_explicit_district_replacement_forms_including_draft_only(self):
        held=plan(H('028'),[pov(S)]);moved=decision(intent='replace_plan',p=wire(plan(H('030'),[pov(S)])))
        for text in ('Use House 30 instead of House 28.','Instead of House 28, use House 30.','Not House 28 - House 30.','Replace House 28 with House 30.'):
            self.assertEqual(self.convert(text,moved,held)['normalized_plan']['district'],H('030'),text)
            self.assertEqual(self.convert(text,moved,None,held)['normalized_plan']['district'],H('030'),text)  # draft-only held
        self.refused('explicit_district_conflict','Replace House 27 with House 30.',moved,held)

    def test_metric_removal_and_replacement_check_the_desired_end_state(self):
        full_and_cmp=plan(H('028'),[profile(None,'s1'),compare('median_age',S,'s2')])
        self.assertIsNone(self.convert('Remove the median age comparison.',decision(intent='replace_plan',p=wire(plan(H('028'),[profile(None,'s1')]))),full_and_cmp)['normalized_plan']['steps'][0]['args']['metric_ids'])
        self.refused('explicit_metric_conflict','Remove the median age comparison.',decision(intent='replace_plan',p=wire(full_and_cmp)),full_and_cmp)  # still present
        cmp_pov=plan(H('028'),[pov(S)]);two=plan(H('028'),[profile(['median_household_income','median_age'])])
        for text,before,after in (('Replace senior poverty with median age.',cmp_pov,[compare('median_age',S)]),
                                  ('Change senior poverty to median household income.',cmp_pov,[compare('median_household_income',S)]),
                                  ('Switch the metric from senior poverty to median age.',cmp_pov,[compare('median_age',S)]),
                                  ('Drop median household income.',two,[profile(['median_age'])]),
                                  ('Show the profile without median age.',two,[profile(['median_household_income'])])):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,decision(intent='replace_plan',p=wire(plan(H('028'),after))),before)['status'],'propose')
                self.refused('explicit_metric_conflict',text,decision(intent='replace_plan',p=wire(before)),before)
        # The replacement target is still required.
        self.refused('explicit_metric_conflict','Replace senior poverty with median age.',decision(intent='replace_plan',p=wire(plan(H('028'),[compare('median_household_income',S)]))),cmp_pov)

    def test_cross_measure_only_for_one_connector_between_measures(self):
        cmp_pov=plan(H('028'),[pov(S)])
        for text,steps,ctx in (('Change senior poverty to median household income.',[compare('median_household_income',S)],cmp_pov),
                               ('Add median household income to the plan and keep senior poverty.',[pov(S),profile(['median_household_income'],'s2')],cmp_pov),
                               ('Compare senior poverty in House 28 to the State and add median age.',[pov(S),profile(['median_age'],'s2')],None),
                               ('Compare senior poverty in House 28 against the State and also show median age.',[pov(S),profile(['median_age'],'s2')],None),
                               ('House 28 senior poverty compared with House 30; add median age.',[pov('HI-HOUSE-030-2024'),profile(['median_age'],'s2')],None)):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,decision(intent='replace_plan' if ctx else 'create_plan',p=wire(plan(H('028'),steps))),ctx)['status'],'propose')
        split=decision(p=wire(plan(H('028'),[pov(S),profile(['median_household_income'],'s2')])))
        for text in ('Compare senior poverty against median household income in House 28.','Compare senior poverty to median income in House 28.',
                     'Senior poverty versus median age for House 28.'):
            self.recovered('unsupported',text,split,reason='unsupported_operation')

    def test_one_held_rule_for_draft_only_map_and_service_area(self):
        draft=plan(H('028'),[pov(S)],map_session=2024,svc='oahu');added=copy.deepcopy(draft);added['steps'].append(compare('median_age',S,'s2'))
        out=self.convert('Also compare median age with the State.',decision(intent='replace_plan',p=wire(added,0)),None,draft)
        self.assertEqual((out['normalized_plan']['map_session'],out['normalized_plan']['service_area_id'],out['inherited_fields']),(2024,'oahu',[]))
        self.refused('explicit_service_area_unstated_change','Also compare median age with the State.',decision(intent='replace_plan',p=wire(dict(added,service_area_id=None),0)),None,draft)

    def test_federal_and_congress_wording_never_becomes_a_state_district(self):
        held=plan(H('028'),[profile(['median_age'])])
        for text in ('Profile median age for US House district 1.','Profile median age for congress district 2.',
                     "Profile median age for Hawaii's 2nd congressional district.",'Profile median age for the congressional seat 2.'):
            for p_,ctx in ((plan(H('001'),[profile(['median_age'])]),None),(plan(H('002'),[profile(['median_age'])]),held)):
                self.recovered('unsupported',text,decision(intent='replace_plan' if ctx else 'create_plan',p=wire(p_)),ctx,reason='unavailable_evidence')
        self.assertEqual(self.convert('Profile median age in House 28 for my congressional testimony.',decision(p=wire(plan(H('028'),[profile(['median_age'])]))))['status'],'propose')

    def test_comparator_district_must_be_named_or_held(self):
        held=plan(H('028'),[pov(S)])
        self.refused('explicit_comparator_unstated','Compare senior poverty with a neighboring district.',decision(intent='replace_plan',p=wire(plan(H('028'),[pov('HI-HOUSE-027-2024')]))),held)
        for gid in ('HI-HOUSE-025-2024','HI-SENATE-025-2024'):
            out=self.recovered('clarify','Compare senior poverty in House 28 versus district 25.',decision(p=wire(plan(H('028'),[pov(gid)]))),field='comparator')
            self.assertEqual([c['value'] for c in out['choices']],['HI-HOUSE-025-2024','HI-SENATE-025-2024'])
        held30=plan(H('028'),[pov('HI-HOUSE-030-2024')]);moved=copy.deepcopy(held30);moved['district']=H('025','senate')
        self.assertEqual(self.convert('Same for Senate 25.',decision(intent='replace_plan',p=wire(moved)),held30)['status'],'propose')  # held comparator

    def test_county_comparator_or_statewide_figure_does_not_change_service_area(self):
        held=plan(H('028'),[pov(S)],svc='oahu')
        for text,gid in (('Compare senior poverty with Maui County.','HI-COUNTY-009-2024'),('Compare senior poverty with the statewide rate.',S)):
            for svc,code in (('maui','explicit_service_area_unstated'),('statewide','explicit_service_area_unstated'),(None,'explicit_service_area_unstated_change')):
                self.refused(code,text,decision(intent='replace_plan',p=wire(plan(H('028'),[pov(gid)],svc=svc))),held)
            self.assertEqual(self.convert(text,decision(intent='replace_plan',p=wire(plan(H('028'),[pov(gid)],svc='oahu'))),held)['normalized_plan']['service_area_id'],'oahu')
        self.assertEqual(self.convert('Use the Maui service area.',decision(intent='replace_plan',p=wire(plan(H('028'),[pov(S)],svc='maui'))),held)['normalized_plan']['service_area_id'],'maui')

    def test_control_conflict_only_blocks_plan_proposals(self):
        held=plan(H('028'),[pov(S)]);draft=plan(H('028'),[pov(S),profile(['median_age'],'s2')])
        out=self.convert('Why that figure?',decision(intent='inspect_source',focus_alias='selected_1'),held,draft,1)
        self.assertEqual((out['status'],out['intent']),('propose','inspect_source'));self.assertTrue(out['source_inspection_refs'])
        self.recovered('clarify','Also add median household income.',decision(intent='replace_plan',p=wire(draft)),held,draft,field='control_conflict')

    def test_negated_constraints_and_benign_words_are_not_unsupported(self):
        ok=decision(p=wire(plan(H('028'),[pov(S)])))
        for text in ('Compare senior poverty in House 28 with the State; no causal claims.','Compare senior poverty in House 28 with the State for our qualifying grant report.',
                     'Compare senior poverty in House 28 with the State without predicting anything.'):
            self.assertEqual(self.convert(text,ok)['status'],'propose',text)
        for text in ('Which residents in House 28 qualify for SNAP?','Does SNAP cause lower senior poverty in House 28?'):
            self.recovered('unsupported',text,ok,reason='unsupported_operation')
        out=self.convert('Profile median age in House 28 using the 2024 legislative districts.',decision(p=wire(plan(H('028'),[profile(['median_age'])]),2024)))
        self.assertEqual(out['normalized_plan']['map_session'],2024)

class SourceReviewJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    setUp=repair.LanguageRepairJobTests.setUp;tearDown=repair.LanguageRepairJobTests.tearDown
    body=repair.LanguageRepairJobTests.body;run_job=repair.LanguageRepairJobTests.run_job
    def test_transport_failures_are_service_errors_and_bad_arguments_are_uncertain(self):
        original=self.provider.transport
        def run(transport):
            self.provider.transport=transport;r=repair.LanguageRepairTests.request(self,'Profile median age in House 28.')
            self.assertEqual(self.service.operator_start(r)[0],202);return self.service.operator_wait(r['request_id'])[1]
        def count_html(method,path,body,secret,deadline):raise LanguageError('invalid_provider_json',503)
        out=run(count_html)
        self.assertEqual((out['status'],out['reason_code'],out['model_calls'],out['attribution']['decision_origin']),('error','',0,'service_failure'))
        self.assertFalse(self.ledger.summary()['unresolved'])
        def gen_html(method,path,body,secret,deadline):
            if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':1000}
            raise LanguageError('invalid_provider_json',503)
        out=run(gen_html)
        self.assertEqual((out['status'],out['model_calls'],out['attribution']['model_status']),('error',1,'not_decoded'))
        self.assertTrue(self.ledger.summary()['unresolved'])  # possible dispatch without known usage keeps liability
        self.provider.transport=original
        out,ev=self.run_job('Profile median age in House 28.','{"status":"propose","intent"')  # truncated strict arguments
        self.assertEqual((out['status'],out['reason_code'],out['attribution']['decision_origin'],out['attribution']['model_status']),
                         ('uncertain','uncertain_interpretation','server_refusal','not_decoded'))

    def test_closed_attribution_separates_model_decisions_from_server_recovery_and_refusal(self):
        snap=wire(plan(H('028'),[{'step_id':'s1','operation':'program_evidence','args':{'program_ids':['snap_hi']}}]))
        cases=[('Compare senior poverty in House 28 with the State.',decision(p=wire(plan(H('028'),[pov(S)]))),'propose','model','propose','create_plan',''),
               ('Show food assistance evidence for House 28.',decision(p=snap),'clarify','server_recovery','propose','create_plan','generic_program_theme'),
               ('Show food assistance evidence for House 28.',decision('clarify','none',clarify_field='program',clarify_choices=['p_snap_hi','p_wic_hi'],reason_code='missing_context'),'clarify','model','clarify','none',''),
               ('Forecast unemployment in House 28.',decision(p=wire(plan(H('028'),[profile(['unemployment_rate'])]))),'unsupported','server_recovery','propose','create_plan','unsupported_inference'),
               ('Forecast unemployment in House 28.',decision('unsupported','none',reason_code='unsupported_operation'),'unsupported','model','unsupported','none',''),
               ('Profile median age in House 28.',decision(p=wire(plan(H('029'),[profile(['median_age'])]))),'uncertain','server_refusal','propose','create_plan',''),
               ('Profile median age in House 28.',decision('uncertain','none',reason_code='uncertain_interpretation'),'uncertain','model','uncertain','none','')]
        for text,d,status,origin,model_status,model_intent,category in cases:
            with self.subTest(text=text,origin=origin):
                out,ev=self.run_job(text,d)
                self.assertEqual((out['status'],out['attribution']),(status,{'decision_origin':origin,'model_status':model_status,'model_intent':model_intent,
                    'recovery_category':category,'failure_class':'local_refusal' if origin=='server_refusal' else 'none'}))
                for key,value in out['attribution'].items():self.assertIn(value,ATTRIBUTION_VALUES[key])
                self.assertFalse({'recovered_from','stage','rejection_code','function_arguments'}&set(out));self.assertNotIn(text,json.dumps(out))

class SourceReviewHttpOperatorTests(unittest.TestCase):
    """Actual WSGI routes and the actual operator CLI rows carry the same closed attribution."""
    def setUp(self):self.f=proposal_fixtures.LanguageProposalTests();self.f.setUp()
    def tearDown(self):self.f.tearDown()
    @patch.dict(os.environ,{'HAIC_LANGUAGE_OPERATOR_CUTOFF_EPOCH':str(int(time.time())+86400)})  # evaluator-supplied future cutoff
    def test_http_status_and_operator_rows_record_attribution_and_origin_counts(self):
        f=self.f;snap={'district':H('028'),'map_session':2026,'issue_id':'custom','service_area_id':None,
            'steps':[{'step_id':'s1','operation':'program_evidence','args':{'program_ids':['snap_hi']}}]}
        f.decisions.append(f.decision(snap));out=f.finish_http(f.request('Show food assistance evidence for House28.'))
        self.assertEqual((out['status'],out['attribution']['decision_origin'],out['attribution']['recovery_category']),('clarify','server_recovery','generic_program_theme'))
        self.assertFalse({'recovered_from','stage','rejection_code'}&set(out))
        tool=Path(__file__).resolve().parents[1]/'tools/ia_language_operator.py'
        spec=importlib.util.spec_from_file_location('ia_operator_source_review',tool);operator=importlib.util.module_from_spec(spec);spec.loader.exec_module(operator)
        rows=[('a','Show food assistance evidence for House28.',f.decision(snap)),('b','Profile median age in House28.',f.decision(f.plan('custom'))),
              ('c','Profile median age in House28.',dict(f.decision(),status='uncertain',intent='none',reason_code='uncertain_interpretation'))]
        questions=f.root/'questions.jsonl';output=f.root/'results.jsonl'
        questions.write_text(''.join(json.dumps({'case_id':cid,'request':f.request(text)})+'\n' for cid,text,_ in rows))
        f.decisions.extend(d for *_,d in rows);captured=io.StringIO()
        with patch.object(operator,'load_core',return_value=f.i.core),patch.object(operator,'FundingLedger',return_value=f.ledger),\
             patch.object(operator,'protected_path',side_effect=lambda path,**kw:Path(path)),\
             patch('districtbrief.ia_language_jobs.OpenAIProvider',return_value=f.provider),redirect_stdout(captured):
            self.assertEqual(operator.main(['smoke','--profile','terra-medium','--questions',str(questions),'--output',str(output)]),0)
        records=[json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual([(r['status'],r['response']['attribution']['decision_origin']) for r in records],[('clarify','server_recovery'),('propose','model'),('uncertain','model')])
        summary=json.loads(captured.getvalue())
        self.assertEqual(summary['terminal_origin_counts'],{'clarify/server_recovery/generic_program_theme':1,'propose/model/-':1,'uncertain/model/-':1})

if __name__=='__main__':unittest.main()

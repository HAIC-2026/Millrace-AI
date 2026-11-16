"""OX integrated-v2 review (v2 -> v3) regressions N1-N9: bounded compare clause and explicit switches, role-noun
fail-closed, negated districts, field-level control-conflict resolution, replacement targets, county comparator
provenance, keyword false positives and closed failure_class attribution. Injected strict-function wire only."""
import copy
import json
import tempfile
import unittest
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.ia_language import LanguageError
from districtbrief.ia_language_jobs import ATTRIBUTION_VALUES, LanguageService
from language_funding_fixture import PROFILE,ledger_fixture
import test_ia_language_repair as repair  # module import: its TestCases are not re-collected here
from test_ia_language_repair import H,plan,compare,profile,wire,decision

S='HI-STATE-2024';MAUI='HI-COUNTY-009-2024'
def pov(geo,sid='s1'):return compare('poverty_rate_65_plus',geo,sid)

class IntegratedReviewGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    request=repair.LanguageRepairTests.request;convert=repair.LanguageRepairTests.convert
    refused=repair.LanguageRepairTests.refused;recovered=repair.LanguageRepairTests.recovered

    def test_n1_switch_after_a_compare_clause_is_the_new_primary(self):
        for held_geo in (S,MAUI):
            held=plan(H('028'),[pov(held_geo)])
            moved=decision(intent='replace_plan',p=wire(plan(H('030'),[pov(held_geo)])))
            as_cmp=decision(intent='replace_plan',p=wire(plan(H('028'),[pov('HI-HOUSE-030-2024')])))
            added=decision(intent='replace_plan',p=wire(plan(H('028'),[pov(held_geo),pov('HI-HOUSE-030-2024','s2')])))
            name='Maui County' if held_geo==MAUI else 'the State'
            for text in (f'Compare it with {name} and switch to House 30.',f'Keep comparing with {name}, then move to House 30.',
                         f'Keep comparing to {name} but change the district to House 30.'):
                with self.subTest(text=text):
                    self.assertEqual(self.convert(text,moved,held)['normalized_plan']['district'],H('030'))
                    self.refused('explicit_district_conflict',text,as_cmp,held)
                    self.refused('explicit_district_conflict',text,added,held)
        # The bounded clause still marks a direct comparator.
        held=plan(H('028'),[pov(S)])
        self.assertEqual(self.convert('Compare senior poverty with House 30.',decision(intent='replace_plan',p=wire(plan(H('028'),[pov('HI-HOUSE-030-2024')]))),held)['status'],'propose')
        # A switch plus an unmarked second district cannot establish roles.
        self.refused('explicit_district_ambiguous','Profile House 28 and switch to House 30.',decision(p=wire(plan(H('030'),[profile(['median_age'])]))))

    def test_n2_role_noun_wording_never_certifies_a_reversed_plan(self):
        # v5 (OX3-1/OX3-4): a role noun that directly governs one mention marks it the comparator; the reversed
        # plan is still refused. Role wording that governs no mention fails closed only with >=2 unmarked districts.
        nat=decision(p=wire(plan(H('028'),[pov('HI-SENATE-025-2024')])));rev=decision(p=wire(plan(H('025','senate'),[pov('HI-HOUSE-028-2024')])))
        for text in ('Using Senate 25 for comparison, show House 28 senior poverty.','Make Senate 25 the comparison for House 28 senior poverty.',
                     'Against the baseline of Senate 25, how is House 28 on senior poverty?','Against a Senate 25 benchmark, measure House 28 senior poverty.',
                     'Senate 25 for comparison: House 28 senior poverty.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,nat)['normalized_plan']['district'],H('028'))
                self.refused('explicit_district_conflict',text,rev)
        for d in (nat,rev):
            self.refused('explicit_district_ambiguous','Show House 28 and Senate 25 senior poverty with the State as the baseline.',d)
        # Attributable cues still decide; "the same ... comparison for" is not a role noun.
        self.assertEqual(self.convert('Senate 25 serves as the comparison for House 28 senior poverty.',nat)['status'],'propose')
        held=plan(H('028'),[pov(S)]);moved=copy.deepcopy(held);moved['district']=H('025','senate')
        self.assertEqual(self.convert('Run the same senior poverty comparison for Senate 25.',decision(intent='replace_plan',p=wire(moved)),held)['status'],'propose')

    def test_n3_negated_district_is_neither_primary_nor_comparator(self):
        held=plan(H('028'),[pov(S)])
        keep=decision(intent='replace_plan',p=wire(held));to30=decision(intent='replace_plan',p=wire(plan(H('030'),[pov(S)])))
        add30=decision(intent='replace_plan',p=wire(plan(H('028'),[pov(S),pov('HI-HOUSE-030-2024','s2')])))
        for text in ('Keep the same plan, but not for House 30.','Compare senior poverty with the State, not with House 30.','Exclude House 30; just compare with the State.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,keep,held)['normalized_plan']['district'],H('028'))
                self.refused('explicit_district_conflict',text,to30,held);self.refused('explicit_district_conflict',text,add30,held)
        # Without a held plan a fully negated mention proves the primary missing.
        self.recovered('clarify','Not House 30.',decision(p=wire(plan(H('030'),[pov(S)]))),field='district')
        # Explicit replacement wording still names old and new.
        self.assertEqual(self.convert('Not House 28 - House 30.',to30,held)['normalized_plan']['district'],H('030'))

    def test_n4_explicit_value_resolves_only_its_conflicting_field(self):
        held=plan(H('028'),[pov(S)]);draft30=plan(H('030'),[pov(S)])
        s5=decision(intent='replace_plan',p=wire(plan(H('005','senate'),[profile(['median_age'])])))
        out=self.convert('Profile median age in Senate 5.',s5,held,draft30)
        self.assertEqual((out['status'],out['normalized_plan']['district']),('propose',H('005','senate')))
        # Unresolved: no district stated; a comparator-only mention; a second conflicting field (map) unstated.
        self.recovered('clarify','Also compare median age with the State.',decision(intent='replace_plan',p=wire(plan(H('028'),[pov(S),compare('median_age',S,'s2')]))),held,draft30,field='control_conflict')
        self.recovered('clarify','Compare senior poverty with Senate 5.',decision(intent='replace_plan',p=wire(plan(H('028'),[pov('HI-SENATE-005-2024')]))),held,draft30,field='control_conflict')
        draft_map=plan(H('030'),[pov(S)],map_session=2024)
        self.recovered('clarify','Profile median age in Senate 5.',s5,held,draft_map,field='control_conflict')
        # The model must report the stated map year (sentinel beside an explicit year is refused, never server-filled).
        self.refused('explicit_map_unreported','Profile median age in Senate 5 on the 2026 map.',s5,held,draft_map)
        s5_2026=decision(intent='replace_plan',p=wire(plan(H('005','senate'),[profile(['median_age'])]),2026))
        out=self.convert('Profile median age in Senate 5 on the 2026 map.',s5_2026,held,draft_map)
        self.assertEqual((out['normalized_plan']['district'],out['normalized_plan']['map_session']),(H('005','senate'),2026))
        # Differing steps are never resolved from wording.
        self.recovered('clarify','Profile median age in Senate 5.',s5,held,plan(H('028'),[profile(['median_age'])]),field='control_conflict')

    def test_n5_replacement_target_and_not_just_are_not_removed(self):
        held=plan(H('028'),[pov(S)])
        for text,metric in (('Replace senior poverty with median age for House 28.','median_age'),
                            ('Change senior poverty to median household income for this comparison.','median_household_income'),
                            ('Switch senior poverty to median age for the State comparison.','median_age')):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,decision(intent='replace_plan',p=wire(plan(H('028'),[compare(metric,S)]))),held)['status'],'propose')
                self.refused('explicit_metric_conflict',text,decision(intent='replace_plan',p=wire(held)),held)  # source kept
        self.assertEqual(self.convert('Show not just median age but also senior poverty for House 28.',decision(p=wire(plan(H('028'),[profile(['median_age','poverty_rate_65_plus'])]))))['status'],'propose')
        self.refused('explicit_metric_conflict','Show not just median age but also senior poverty for House 28.',decision(p=wire(plan(H('028'),[profile(['poverty_rate_65_plus'])]))))
        two=plan(H('028'),[profile(['median_age','median_household_income'])])
        self.assertEqual(self.convert('Swap median age for median gross rent.',decision(intent='replace_plan',p=wire(plan(H('028'),[profile(['median_household_income','median_gross_rent'])]))),two)['status'],'propose')
        self.refused('explicit_metric_conflict','Swap median age for median gross rent.',decision(intent='replace_plan',p=wire(two)),two)

    def test_n6_county_comparator_must_be_named_or_held(self):
        held=plan(H('028'),[pov(S)])
        for text,gid in (('Compare senior poverty with its county.','HI-COUNTY-003-2024'),('Compare senior poverty with a nearby county.',MAUI)):
            self.refused('explicit_comparator_unstated',text,decision(intent='replace_plan',p=wire(plan(H('028'),[pov(gid)]))),held)
        for text,gid in (('Compare senior poverty with Maui County.',MAUI),('Compare senior poverty with the City and County of Honolulu.','HI-COUNTY-003-2024')):
            self.assertEqual(self.convert(text,decision(intent='replace_plan',p=wire(plan(H('028'),[pov(gid)]))),held)['status'],'propose')
        heldM=plan(H('028'),[pov(MAUI)]);moved=copy.deepcopy(heldM);moved['district']=H('025','senate')
        self.assertEqual(self.convert('Same for Senate 25.',decision(intent='replace_plan',p=wire(moved)),heldM)['status'],'propose')  # held comparator

    def test_n7_keyword_false_positives_and_true_positives(self):
        ok=decision(p=wire(plan(H('028'),[pov(S)])))
        for text in ('Compare senior poverty in House 28 with the State for my congressional report.','Show us House district 28 senior poverty compared with the State.',
                     'Compare senior poverty in House 28 with the State; I will predict nothing.'):
            self.assertEqual(self.convert(text,ok)['status'],'propose',text)
        for text,reason in (('Profile median age for US House district 1.','unavailable_evidence'),('Profile median age for the US Congress seat 1.','unavailable_evidence'),
                            ('Forecast senior poverty in House 28.','unsupported_operation')):
            self.recovered('unsupported',text,decision(p=wire(plan(H('001'),[profile(['median_age'])]))),reason=reason)

    def test_n9_comparator_chamber_clarification_has_its_own_category(self):
        out=self.convert('Compare senior poverty in House 28 versus district 25.',decision(p=wire(plan(H('028'),[pov('HI-SENATE-025-2024')]))))
        self.assertEqual((out['status'],out['clarify_field'],out['recovery_category']),('clarify','comparator','ambiguous_comparator_chamber'))

class IntegratedReviewJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    setUp=repair.LanguageRepairJobTests.setUp;tearDown=repair.LanguageRepairJobTests.tearDown
    body=repair.LanguageRepairJobTests.body
    def run_raw(self,body=None,raises=None):
        def transport(method,path,b,secret,deadline):
            if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':1000}
            if raises:raise raises
            return 200,body
        # Fresh synthetic ledger per case: a timeout correctly retains liability and would halt the next job.
        self.service.close();tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.ledger=ledger_fixture(tmp.name)
        self.service=LanguageService(self.i,enabled=True,ledger=self.ledger,provider=self.provider)
        self.provider.transport=transport;r=repair.LanguageRepairTests.request(self,'Profile median age in House 28.')
        self.assertEqual(self.service.operator_start(r)[0],202);return self.service.operator_wait(r['request_id'])[1]
    def test_n8_closed_failure_class_distinguishes_refusal_incomplete_deadline_transport(self):
        ok=decision(p=wire(plan(H('028'),[profile(['median_age'])])))
        refusal=dict(self.body(ok),output=[{'type':'message','id':'msg','content':[{'type':'refusal','refusal':'RESIDENT-CANARY'}]}])
        cases=[(dict(self.body(ok),status='incomplete'),None,'error','service_failure','incomplete_output'),
               (refusal,None,'error','model_refusal','provider_refusal'),
               (dict(self.body(ok),output=[]),None,'error','service_failure','invalid_output'),
               (None,LanguageError('provider_timeout',503),'error','service_failure','deadline'),
               (None,LanguageError('provider_transport_error',503),'error','service_failure','transport'),
               (None,LanguageError('invalid_provider_json',503),'error','service_failure','transport'),
               (self.body('{"status":"propose"'),None,'uncertain','server_refusal','invalid_arguments'),
               (self.body(ok),None,'propose','model','none')]
        for body,raises,status,origin,failure in cases:
            with self.subTest(failure=failure):
                out=self.run_raw(body,raises)
                self.assertEqual((out['status'],out['attribution']['decision_origin'],out['attribution']['failure_class']),(status,origin,failure))
                for key,value in out['attribution'].items():self.assertIn(value,ATTRIBUTION_VALUES[key])
                self.assertNotIn('CANARY',json.dumps(out));self.assertEqual(out['reason_code'],'' if status=='error' else out['reason_code'])

if __name__=='__main__':unittest.main()

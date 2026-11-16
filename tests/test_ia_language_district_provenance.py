"""F1: deterministic district/chamber provenance and generic-poverty ambiguity (injected decisions, no network)."""
import copy
import json
import unittest
import uuid
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.interpret import recipe
from districtbrief.ia_language import (SCHEMA_VERSION,LanguageError,convert_decision,prepare_request,wire_plan)
import test_ia_language_map_default as map_tests  # module import: its TestCase is not re-collected here

H28={'state_fips':'15','chamber':'house','code':'028','boundary_session':2024}
def plan(district=H28,steps=None):
    return {'district':dict(district),'map_session':2026,'issue_id':'custom','service_area_id':None,
            'steps':steps or [{'step_id':'s1','operation':'profile','args':{'metric_ids':['median_age']}}]}
def d(chamber,code):return dict(H28,chamber=chamber,code=code)
def compare(metric):return [{'step_id':'s1','operation':'compare','args':{'metric_ids':[metric],'comparison_geography':'HI-STATE-2024'}}]

class DistrictProvenanceTests(unittest.TestCase):
    job=map_tests.MapDefaultTests.job
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    def request(self,text,confirmed=None,draft='same'):
        draft=copy.deepcopy(confirmed) if draft=='same' else draft
        held=confirmed or draft
        return {'schema_version':SCHEMA_VERSION,'request_id':str(uuid.uuid4()),'utterance':text,'context':{
            'case_id':str(uuid.uuid4()),'branch_id':str(uuid.uuid4()),'revision':1,'snapshot_id':self.i.snapshot_id,
            'operation_version':'ia-core/1','recipe_version':(held['issue_id'] if held else 'custom')+'/1',
            'confirmed_plan':copy.deepcopy(confirmed),'draft_plan':copy.deepcopy(draft),'focused_step_id':None,'selected_claim_refs':[]}}
    def decision(self,proposal,intent):
        return {'status':'propose','intent':intent,'plan':wire_plan(proposal),'focus_alias':'','clarify_field':'',
                'clarify_choices':[],'reason_code':'','inherited_fields':[]}
    def convert(self,text,proposal,confirmed=None,draft='same'):
        intent='replace_plan' if confirmed or (draft not in (None,'same')) else 'create_plan'
        p=prepare_request(self.request(text,confirmed,draft),self.i,'s')
        return convert_decision(p,self.decision(proposal,intent),self.i.core)
    def refused(self,code,*args,**kw):
        with self.assertRaises(LanguageError) as c:self.convert(*args,**kw)
        self.assertEqual(c.exception.code,code)
    def recovered(self,code,field,*args,**kw):
        # A request/context-proven condition: fixed typed clarification, never a proposal.
        out=self.convert(*args,**kw);self.assertEqual((out.pop('recovered_from'),out['status'],out['clarify_field']),(code,'clarify',field))
        self.assertIsNone(out['normalized_plan']);self.assertEqual(out['intent'],'none');self.assertTrue(out['choices'])
        return out

    def test_ox_f1_repros_refused(self):
        # repair-1 progressive clarification: no number and no stated chamber asks the chamber first.
        self.recovered('explicit_district_missing','chamber','Compare senior poverty with the State.',plan(H28,compare('poverty_rate_65_plus')))
        moved=plan(d('house','029'),[*plan()['steps'],{'step_id':'s2','operation':'profile','args':{'metric_ids':['median_household_income']}}])
        self.refused('explicit_district_unstated_change','Also add median household income.',moved,plan())
        self.recovered('explicit_district_missing','district','Profile median age for a senate district.',plan(d('senate','025')))
        self.recovered('explicit_metric_ambiguous','metric','Compare poverty in Senate 25 with the State.',plan(d('senate','025'),compare('poverty_rate_65_plus')))
        self.recovered('explicit_metric_ambiguous','metric','Compare poverty in Senate 25 with the State.',plan(d('senate','025'),compare('poverty_rate_all_people')))
        # Existing controls unchanged.
        self.refused('explicit_district_conflict','Same for Senate 25.',moved,plan())
        reversed_=plan(d('senate','025'),[{'step_id':'s1','operation':'compare','args':{'metric_ids':['poverty_rate_65_plus'],'comparison_geography':'HI-HOUSE-028-2024'}}])
        self.refused('explicit_district_conflict','Senior poverty: House 28 minus Senate 25.',reversed_)

    def test_confirmed_inheritance_and_explicit_replacement_accepted(self):
        kept=plan(H28,[*plan()['steps'],{'step_id':'s2','operation':'profile','args':{'metric_ids':['median_household_income']}}])
        out=self.convert('Also add median household income.',kept,plan())
        self.assertEqual(out['normalized_plan']['district'],H28);self.assertIn('district',out['inherited_fields'])
        self.assertNotIn('district',[x['field'] for x in out['typed_diff']])
        out=self.convert('Replace House 28 with Senate 25.',plan(d('senate','025')),plan())
        self.assertEqual(out['normalized_plan']['district'],d('senate','025'));self.assertNotIn('district',out['inherited_fields'])
        out=self.convert('Profile median age for Senate 25.',plan(d('senate','025')),plan())  # explicit move
        self.assertEqual(out['normalized_plan']['district']['code'],'025')
        out=self.convert('Profile median age for Senate district 16.',plan(d('senate','016')))  # explicit, no context
        self.assertEqual(out['normalized_plan']['district'],d('senate','016'))
        # Named aging recipe with confirmed context keeps the held district.
        aging=recipe(H28);out=self.convert('Run the aging at home plan.',aging,plan())
        self.assertEqual(out['normalized_plan']['district'],H28)

    def test_abbreviation_and_bare_number(self):
        self.assertEqual(self.convert('Profile median age for HD 28.',plan())['normalized_plan']['district'],H28)
        self.assertEqual(self.convert('Profile median age for SD-25.',plan(d('senate','025')))['normalized_plan']['district']['chamber'],'senate')
        self.refused('explicit_district_conflict','Profile median age for HD 28.',plan(d('house','029')))
        out=self.convert('Profile median age for district 29 instead.',plan(d('house','029')),plan())  # chamber from held context
        self.assertEqual(out['normalized_plan']['district'],d('house','029'))
        # repair-1 v2: a bare 1-25 number never borrows the held chamber; it clarifies both chambers' district 19.
        self.recovered('explicit_district_missing','district','Profile median age for district 19 instead.',plan(d('senate','019')),plan())
        self.recovered('explicit_district_missing','district','Profile median age for district 12.',plan(d('house','012')))  # no chamber anywhere
        out=self.convert('Profile median age for the senate, district 12.',plan(d('senate','012')))
        self.assertEqual(out['normalized_plan']['district'],d('senate','012'))

    def test_chamber_only_never_selects_a_code(self):
        self.recovered('explicit_district_missing','district','Profile median age for a house district.',plan())
        self.refused('explicit_district_conflict','Show this for the senate district.',plan(),plan())  # keeps House but asks Senate
        self.refused('explicit_district_unstated_change','Show this for the senate district.',plan(d('senate','014')),plan())
        s25=plan(d('senate','025'))
        self.assertEqual(self.convert('Show median age for this senate district.',s25,s25)['normalized_plan']['district'],d('senate','025'))

    def test_unconfirmed_draft_context_and_conflict(self):
        draft=plan()
        out=self.convert('Also add median household income.',plan(H28,[*draft['steps'],{'step_id':'s2','operation':'profile','args':{'metric_ids':['median_household_income']}}]),None,draft)
        self.assertEqual(out['normalized_plan']['district'],H28);self.assertEqual(out['inherited_fields'],[])  # draft is not confirmed inheritance
        self.refused('explicit_district_unstated_change','Also add median household income.',plan(d('house','029')),None,draft)
        # Divergent confirmed/draft districts never become confirmed: explicit choice is required.
        self.recovered('control_conflict','control_conflict','Also add median age.',plan(),plan(),plan(d('house','029')))
        self.recovered('control_conflict','control_conflict','Also add median age.',plan(d('house','029')),plan(),plan(d('house','029')))
        # N4: an explicit complete value resolves the conflicting field it states (district only differs here).
        out=self.convert('Profile House 29 median age.',plan(d('house','029')),plan(),plan(d('house','029')))
        self.assertEqual(out['normalized_plan']['district'],d('house','029'));self.assertNotIn('district',out['inherited_fields'])
        self.refused('explicit_district_conflict','Profile House 29 median age.',plan(),plan(),plan(d('house','029')))

    def test_generic_poverty_needs_named_population_or_held_metric(self):
        s25=d('senate','025')
        self.assertEqual(self.convert('Compare senior poverty in Senate 25 with the State.',plan(s25,compare('poverty_rate_65_plus')))['normalized_plan']['steps'][0]['args']['metric_ids'],['poverty_rate_65_plus'])
        self.convert('Compare the overall poverty rate in Senate 25 with the State.',plan(s25,compare('poverty_rate_all_people')))
        held=plan(H28,compare('poverty_rate_65_plus'))
        self.convert('Compare poverty with the State again.',held,held)  # poverty metric already in confirmed context
        self.convert('Compare poverty with the State again.',held,None,held)  # visible draft
        self.recovered('explicit_metric_ambiguous','metric','Compare poverty with the State again.',plan(H28,compare('poverty_rate_all_people')),held)
        self.convert('Profile median age for Senate 25.',plan(s25))  # no poverty wording: no effect
        # A population stated on either side names one measure; a mismatched measure is refused.
        self.convert('Compare kūpuna poverty in Senate 25 with the State.',plan(s25,compare('poverty_rate_65_plus')))
        self.convert('Compare poverty for all ages in Senate 25 with the State.',plan(s25,compare('poverty_rate_all_people')))
        self.refused('explicit_metric_conflict','Compare kupuna poverty in Senate 25 with the State.',plan(s25,compare('poverty_rate_all_people')))
        # A named admitted recipe's canonical poverty metric is its documented default.
        self.assertEqual(self.convert('Run the aging at home plan for House 28, including poverty.',recipe(H28))['normalized_plan']['issue_id'],'aging_at_home')

    def test_recipe_default_needs_utterance_or_held_recipe_not_model_issue(self):
        # FH F1b: the model's own issue_id never launders a self-chosen poverty measure.
        s25=d('senate','025');u='Compare poverty in Senate 25 with the State.'
        aging=dict(plan(s25,compare('poverty_rate_65_plus')),issue_id='aging_at_home')
        food=dict(plan(s25,compare('poverty_rate_all_people')),issue_id='food_assistance_outreach')
        self.recovered('explicit_metric_ambiguous','metric',u,plan(s25,compare('poverty_rate_65_plus')))
        self.recovered('explicit_metric_ambiguous','metric',u,aging)
        self.recovered('explicit_metric_ambiguous','metric',u,food)
        held=plan()  # confirmed custom House 028 without poverty
        moved=dict(plan(H28,[*held['steps'],{'step_id':'s2','operation':'compare','args':{'metric_ids':['poverty_rate_65_plus'],'comparison_geography':'HI-STATE-2024'}}]),issue_id='aging_at_home')
        self.recovered('explicit_metric_ambiguous','metric','Also compare poverty with the State.',moved,held)
        # Legitimate: recipe named in the utterance, or already held by confirmed / unconflicted draft context.
        # repair-1 v4: a named recipe is a default, never a server rule: the full and the partial form both validate.
        self.convert('Run the aging at home plan for Senate 25 and compare poverty with the State.',recipe(s25))
        self.convert('Run the aging at home plan for Senate 25 and compare poverty with the State.',aging)
        held_aging=dict(plan(H28),issue_id='aging_at_home')
        kept=dict(plan(H28,[*held_aging['steps'],{'step_id':'s2','operation':'compare','args':{'metric_ids':['poverty_rate_65_plus'],'comparison_geography':'HI-STATE-2024'}}]),issue_id='aging_at_home')
        self.convert('Also compare poverty with the State.',kept,held_aging)
        self.convert('Also compare poverty with the State.',kept,None,held_aging)

    def test_directed_replacement_with_aliases_and_ambiguous_mentions(self):
        # FH A2: the replacement TARGET is selected whatever the alias form; the stale SOURCE is refused.
        s25=plan(d('senate','025'))
        for text in ('Replace HD 28 with SD 25.','Replace House 28 with SD 25.','Replace HD 28 with Senate 25.','Replace House 28 with Senate 25.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,s25,plan())['normalized_plan']['district'],d('senate','025'))
                self.refused('explicit_district_conflict',text,plan(),plan())
        self.refused('explicit_district_conflict','Replace HD 27 with SD 25.',s25,plan())  # wrong source vs confirmed
        self.assertEqual(self.convert('Move from House 28 to House 29.',plan(d('house','029')),plan())['normalized_plan']['district']['code'],'029')
        self.refused('explicit_district_conflict','Move from House 28 to House 29.',plan(),plan())
        self.refused('explicit_district_ambiguous','Profile median age for House 28 and House 29.',plan())
        self.refused('explicit_district_ambiguous','Profile median age for HD 28 and SD 25.',s25)
        cmp25=plan(H28,[{'step_id':'s1','operation':'compare','args':{'metric_ids':['median_age'],'comparison_geography':'HI-SENATE-025-2024'}}])
        self.assertEqual(self.convert('Compare HD 28 median age with SD 25.',cmp25)['normalized_plan']['district'],H28)
        self.refused('explicit_comparator_conflict','Compare HD 28 median age with SD 24.',cmp25)

    def test_refusals_are_typed_clarifications_through_job(self):
        # A guessed district/poverty measure is never proposed; the server returns fixed typed choices.
        for text,proposal,field,choices in (('Compare senior poverty with the State.',plan(H28,compare('poverty_rate_65_plus')),'chamber',2),  # repair-1: was 76 districts
                              ('Profile median age for a senate district.',plan(d('senate','025')),'district',25),
                              ('Compare poverty in Senate 25 with the State.',plan(d('senate','025'),compare('poverty_rate_65_plus')),'metric',2)):
            out=self.job(self.request(text),json.dumps(self.decision(proposal,'create_plan')))
            self.assertEqual((out['status'],out['reason_code'],out['model_calls'],out['clarify_field']),('clarify','missing_context',1,field))
            self.assertEqual(len(out['choices']),choices);self.assertTrue(all(c['field']==field for c in out['choices']))
            self.assertIsNone(out.get('normalized_plan'));self.assertNotIn('recovered_from',out)
        out=self.job(self.request('Profile median age for district 12.'),json.dumps(self.decision(plan(d('house','012')),'create_plan')))
        self.assertEqual([c['alias'] for c in out['choices']],['d_h012','d_s012'])  # number kept, chamber asked
        out=self.job(self.request('Profile median age for House 28.'),json.dumps(self.decision(plan(d('house','029')),'create_plan')))
        self.assertEqual((out['status'],out['reason_code']),('uncertain','uncertain_interpretation'))  # wrong district: no recovery
        out=self.job(self.request('Profile median age for Senate 25.'),json.dumps(self.decision(plan(d('senate','025')),'create_plan')))
        self.assertEqual((out['status'],out['normalized_plan']['district']['code']),('propose','025'))

if __name__=='__main__':unittest.main()

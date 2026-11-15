"""Comparator-clarification tool contract (v9; universe superseded in v10): every already-admitted catalog geography
(State, counties, House and Senate districts) is a typed comparator clarification choice with its canonical ID. A
choice is not a Plan: committed comparators still need provenance. Wrong-field, mixed and out-of-catalog aliases are
rejected. Synthetic only."""
import copy
import json
import unittest
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.ia_language import LanguageError,convert_decision,prepare_request
import test_ia_language_repair as repair  # module import: its TestCases are not re-collected here
from test_ia_language_repair import H,plan,compare,wire,decision

STATE_COUNTY=['HI-COUNTY-001-2024','HI-COUNTY-003-2024','HI-COUNTY-005-2024','HI-COUNTY-007-2024','HI-COUNTY-009-2024','HI-STATE-2024']

class ComparatorChoiceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    request=repair.LanguageRepairTests.request;convert=repair.LanguageRepairTests.convert
    refused=repair.LanguageRepairTests.refused
    def prepared(self,text,confirmed=None):return prepare_request(self.request(text,confirmed),self.i,'s')
    def comparators(self,p):return [(a,c['value']) for a,c in p['choices'].items() if c['field']=='comparator']

    def test_named_legislative_alternatives_are_typed_comparator_choices(self):
        for text in ('Compare median age in House 1 with House 2 or Senate 3.','Compare median age in HD 1 with HD 2 or SD 3.',
                     'Compare median age in House 1 with House district 2 or Senate district number 3.'):
            with self.subTest(text=text):
                p=self.prepared(text);comps=self.comparators(p)
                values=[v for _,v in comps]
                self.assertEqual(values,sorted(values))  # deterministic order
                self.assertTrue({'HI-HOUSE-002-2024','HI-SENATE-003-2024'}<=set(values))
                self.assertEqual([v for v in values if v.startswith(('HI-STATE','HI-COUNTY'))],STATE_COUNTY)  # unchanged State/county
                for alias,value in comps:
                    self.assertEqual(alias,'g_'+value);self.assertIn(value,p['provider_context']['catalog']['geographies'])
                    self.assertIn(alias,p['schema']['properties']['clarify_choices']['items']['enum'])
        # v10: the clarification universe is the full admitted catalog for every request (named or not), never more.
        held=plan(H('028'),[compare('median_age','HI-SENATE-025-2024')])
        for text,ctx in (('Compare median age in House 1 with another district.',None),('Compare median age in House 1 with the State.',None),
                         ('Same for House 12.',held),('Profile House 28.',None)):
            p=self.prepared(text,ctx);values=[v for _,v in self.comparators(p)]
            self.assertEqual(values,sorted(p['provider_context']['catalog']['geographies']),text)
            self.assertEqual(len(values),82);self.assertEqual(sum('-HOUSE-' in v for v in values),51);self.assertEqual(sum('-SENATE-' in v for v in values),25)

    def test_model_typed_comparator_clarification_validates_and_bad_aliases_refuse(self):
        text='Compare median age in HD 1 with HD 2 or SD 3.'
        ok=decision('clarify','none',clarify_field='comparator',clarify_choices=['g_HI-HOUSE-002-2024','g_HI-SENATE-003-2024'],reason_code='ambiguous_reference')
        out=self.convert(text,ok)
        self.assertEqual((out['status'],out['clarify_field'],out['normalized_plan'],out['typed_diff']),('clarify','comparator',None,[]))
        self.assertEqual([(c['field'],c['value']) for c in out['choices']],[('comparator','HI-HOUSE-002-2024'),('comparator','HI-SENATE-003-2024')])
        mixed=decision('clarify','none',clarify_field='comparator',clarify_choices=['g_HI-STATE-2024','g_HI-SENATE-003-2024'],reason_code='missing_context')
        self.assertEqual([c['value'] for c in self.convert(text,mixed)['choices']],['HI-STATE-2024','HI-SENATE-003-2024'])
        self.refused('invalid_clarification',text,dict(ok,clarify_field='district'))           # wrong field for g_ aliases
        self.refused('invalid_clarification',text,dict(ok,clarify_choices=['d_h002','g_HI-SENATE-003-2024']))  # mixed fields
        for alias in ('g_HI-SENATE-026-2024','g_HI-HOUSE-052-2024','g_HI-COUNTY-999-2024','g_HI-HOUSE-2-2024','g_House 2'):
            self.refused('invalid_provider_enum',text,dict(ok,clarify_choices=[alias]))  # outside the admitted catalog
        # An unnamed district is a valid CLARIFICATION choice (v10 universe) but never a committed comparator.
        generic='Compare median age in House 1 with another district.'
        out=self.convert(generic,dict(ok,clarify_choices=['g_HI-HOUSE-002-2024','g_HI-SENATE-009-2024']))
        self.assertEqual((out['status'],[c['value'] for c in out['choices']],out['normalized_plan']),('clarify',['HI-HOUSE-002-2024','HI-SENATE-009-2024'],None))
        self.refused('explicit_comparator_unstated',generic,decision(p=wire(plan(H('001'),[compare('median_age','HI-HOUSE-002-2024')]))))

    def test_comparator_proposals_keep_their_guard_outcomes(self):
        text='Compare median age in HD 1 with SD 3.'
        self.assertEqual(self.convert(text,decision(p=wire(plan(H('001'),[compare('median_age','HI-SENATE-003-2024')]))))['status'],'propose')
        self.refused('explicit_comparator_conflict',text,decision(p=wire(plan(H('001'),[compare('median_age','HI-HOUSE-009-2024')]))))
        self.refused('explicit_district_conflict',text,decision(p=wire(plan(H('003','senate'),[compare('median_age','HI-HOUSE-001-2024')]))))

class ComparatorChoiceJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    setUp=repair.LanguageRepairJobTests.setUp;tearDown=repair.LanguageRepairJobTests.tearDown
    body=repair.LanguageRepairJobTests.body;run_job=repair.LanguageRepairJobTests.run_job
    def test_job_returns_typed_legislative_comparator_clarification_attributed_to_model(self):
        d=decision('clarify','none',clarify_field='comparator',clarify_choices=['g_HI-HOUSE-002-2024','g_HI-SENATE-003-2024'],reason_code='ambiguous_reference')
        out,ev=self.run_job('Compare median age in HD 1 with HD 2 or SD 3.',d)
        self.assertEqual((out['status'],out['clarify_field'],out['normalized_plan']),('clarify','comparator',None))
        self.assertEqual([c['value'] for c in out['choices']],['HI-HOUSE-002-2024','HI-SENATE-003-2024'])
        self.assertEqual(out['attribution'],{'decision_origin':'model','model_status':'clarify','model_intent':'none','recovery_category':'','failure_class':'none'})
        self.assertNotIn('HD 1',json.dumps(out))

if __name__=='__main__':unittest.main()

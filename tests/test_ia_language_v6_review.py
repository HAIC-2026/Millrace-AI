"""OX final-source-v6 review (v7 -> v8) regression V6-1: a negative token anywhere earlier in the same bounded
clause negates a removal/avoidance verb (incl. stop/no longer), so neither keep nor drop is accepted. Single
negation removals and negations in a separate clause still remove. Injected decisions only."""
import unittest
from public_app import load_core
from districtbrief.investigation import Investigation
import test_ia_language_repair as repair  # module import: its TestCases are not re-collected here
from test_ia_language_repair import H,plan,compare,wire,decision

S='HI-STATE-2024'
def pov(geo,sid='s1'):return compare('poverty_rate_65_plus',geo,sid)

class V6ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    request=repair.LanguageRepairTests.request;convert=repair.LanguageRepairTests.convert
    refused=repair.LanguageRepairTests.refused
    def setUp(self):
        self.both=plan(H('028'),[pov(S,'s1'),pov('HI-HOUSE-030-2024','s2')])
        self.keep=decision(intent='replace_plan',p=wire(self.both))
        self.drop=decision(intent='replace_plan',p=wire(plan(H('028'),[pov(S,'s1')])))

    def test_negated_removal_anywhere_in_the_bounded_clause_refuses_keep_and_drop(self):
        for text in ("Don't stop comparing with House 30.",'Never stop comparing against House 30.',"Please don't ever remove House 30.",
                     'Compare with the State without excluding House 30.',"There's no reason to remove the comparison with House 30.",
                     "You shouldn't remove the comparison with House 30.",'You shouldn’t remove the comparison with House 30.',
                     "Don't remove the comparison with House 30.",'Do not drop House 30.',"Don't skip the comparison with House 30."):
            for d in (self.keep,self.drop):
                with self.subTest(text=text):self.refused('explicit_comparator_removal_ambiguous',text,d,self.both)

    def test_single_negation_removals_and_separate_clauses_still_remove(self):
        for text in ('Stop comparing with House 30.','No longer compare against House 30.','Remove the comparison with House 30.',
                     'No, remove the comparison with House 30.','If it is not needed, remove the comparison with House 30.',
                     "Don't compare with House 30 anymore.",'Avoid comparing with House 30.'):
            with self.subTest(text=text):
                self.assertEqual([s['args']['comparison_geography'] for s in self.convert(text,self.drop,self.both)['normalized_plan']['steps']],[S])
                self.refused('explicit_district_conflict',text,self.keep,self.both)

if __name__=='__main__':unittest.main()

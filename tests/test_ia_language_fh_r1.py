"""FH final-source-v5 residual R1 (v6 -> v7): with two or more DISTINCT districts and no comparator role
established, mention order never picks the primary; both orderings fail closed. Injected decisions only."""
import unittest
from public_app import load_core
from districtbrief.investigation import Investigation
import test_ia_language_repair as repair  # module import: its TestCases are not re-collected here
from test_ia_language_repair import H,plan,compare,profile,wire,decision

S='HI-STATE-2024'
def age(geo,sid='s1'):return compare('median_age',geo,sid)

class FhR1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    request=repair.LanguageRepairTests.request;convert=repair.LanguageRepairTests.convert
    refused=repair.LanguageRepairTests.refused

    def test_unproven_roles_between_two_districts_fail_closed_for_both_orderings(self):
        h12_vs_s7=decision(p=wire(plan(H('012'),[age('HI-SENATE-007-2024')])));s7_vs_h12=decision(p=wire(plan(H('007','senate'),[age('HI-HOUSE-012-2024')])))
        for text in ('Compare median age using Senate 7 as the median-age benchmark for House 12.',  # modifier hides the role noun
                     'Compare median age: Senate 7 is our yardstick for House 12.',                 # unknown comparator-first cue
                     'Compare House 12 and Senate 7 on median age.',                                # no role at all
                     'Compare median age for House 12 with the comparator being Senate 7.'):        # unparsed role wording (was a first-mention guess)
            for d in (h12_vs_s7,s7_vs_h12):
                with self.subTest(text=text):self.refused('explicit_district_ambiguous',text,d)

    def test_established_roles_and_single_district_outcomes_are_unchanged(self):
        h12_vs_s7=decision(p=wire(plan(H('012'),[age('HI-SENATE-007-2024')])));s7_vs_h12=decision(p=wire(plan(H('007','senate'),[age('HI-HOUSE-012-2024')])))
        for text in ('Compare median age in House 12 with Senate 7.','Median age: House 12 minus Senate 7.',
                     'Compare median age using Senate 7 as the benchmark for House 12.',
                     'Relative to Senate 7, how does House 12 compare on median age?'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,h12_vs_s7)['normalized_plan']['district'],H('012'))
                self.refused('explicit_district_conflict',text,s7_vs_h12)
        held=plan(H('028'),[age(S)])
        self.assertEqual(self.convert('Make House 30 the comparator.',decision(intent='replace_plan',p=wire(plan(H('028'),[age('HI-HOUSE-030-2024')]))),held)['normalized_plan']['district'],H('028'))
        # One distinct district (even mentioned twice) with no cue stays the primary.
        for text in ('Compare median age in House 12 with the State.','Profile House 12, then compare House 12 median age with the State.'):
            self.assertEqual(self.convert(text,decision(p=wire(plan(H('012'),[age(S)]))))['normalized_plan']['district'],H('012'),text)
        # Explicit replacement and navigation still name the new primary.
        moved=decision(intent='replace_plan',p=wire(plan(H('030'),[age(S)])))
        for text in ('Replace House 28 with House 30.','Compare it with the State and switch to House 30.'):
            self.assertEqual(self.convert(text,moved,held)['normalized_plan']['district'],H('030'),text)

if __name__=='__main__':unittest.main()

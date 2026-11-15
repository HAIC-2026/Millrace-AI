"""OX source-v3 review (v4 -> v5) regressions OX3-1..OX3-5: governed comparator role nouns, negated compare verbs,
bounded role fail-closed, possessive county, explicit chamber/number syntax, "predict no change". Injected decisions."""
import unittest
from public_app import load_core
from districtbrief.investigation import Investigation
import test_ia_language_repair as repair  # module import: its TestCases are not re-collected here
from test_ia_language_repair import H,plan,compare,profile,wire,decision

S='HI-STATE-2024'
def pov(geo,sid='s1'):return compare('poverty_rate_65_plus',geo,sid)

class Ox3ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    request=repair.LanguageRepairTests.request;convert=repair.LanguageRepairTests.convert
    refused=repair.LanguageRepairTests.refused;recovered=repair.LanguageRepairTests.recovered

    def test_ox3_1_comparator_edits_keep_the_held_primary(self):
        held=plan(H('028'),[pov(S)])
        c30=decision(intent='replace_plan',p=wire(plan(H('028'),[pov('HI-HOUSE-030-2024')])))
        m30=decision(intent='replace_plan',p=wire(plan(H('030'),[pov(S)])))
        for text in ('Change the comparator to House 30.','Make House 30 the comparator.','Set the comparison district to House 30.',
                     'Use House 30 as comparator instead of the State.','Use House 30 for comparison.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,c30,held)['normalized_plan']['district'],H('028'))
                self.refused('explicit_district_conflict',text,m30,held)
        # The N1 bounded clause and explicit switch are unchanged: "change the district to X" still moves the primary.
        self.assertEqual(self.convert('Keep comparing to the State but change the district to House 30.',m30,held)['normalized_plan']['district'],H('030'))
        self.refused('explicit_district_conflict','Keep comparing to the State but change the district to House 30.',c30,held)

    def test_ox3_2_negated_compare_verb_excludes_the_mention(self):
        both=plan(H('028'),[pov(S,'s1'),pov('HI-HOUSE-030-2024','s2')])
        drop=decision(intent='replace_plan',p=wire(plan(H('028'),[pov(S,'s1')])));keep=decision(intent='replace_plan',p=wire(both))
        move=decision(intent='replace_plan',p=wire(plan(H('030'),[pov(S,'s1')])))
        for text in ("Don't compare with House 30 anymore.",'Do not compare it to House 30.','Stop comparing with House 30.',
                     'No longer compare against House 30.','Don’t compare to House 30.'):
            with self.subTest(text=text):
                out=self.convert(text,drop,both)
                self.assertEqual((out['normalized_plan']['district'],[s['args']['comparison_geography'] for s in out['normalized_plan']['steps']]),(H('028'),[S]))
                self.refused('explicit_district_conflict',text,keep,both);self.refused('explicit_district_conflict',text,move,both)
        # A positive compare clause is still a comparator cue.
        self.assertEqual(self.convert('Compare senior poverty with House 30.',keep,both)['status'],'propose')

    def test_ox3_4_role_wording_fails_closed_only_with_unattributed_districts(self):
        ok=decision(p=wire(plan(H('028'),[pov(S)])))
        for text in ('Compare senior poverty in House 28 with the State as the baseline.','Compare House 28 senior poverty to the State for reference.'):
            self.assertEqual(self.convert(text,ok)['normalized_plan']['district'],H('028'),text)
        for d in (decision(p=wire(plan(H('028'),[pov('HI-SENATE-025-2024')]))),decision(p=wire(plan(H('025','senate'),[pov('HI-HOUSE-028-2024')])))):
            self.refused('explicit_district_ambiguous','Show House 28 and Senate 25 senior poverty with the State as the baseline.',d)

    def test_ox3_5_possessive_county_district_syntax_and_prediction(self):
        held=plan(H('028'),[pov(S)])
        self.assertEqual(self.convert("Compare senior poverty with Maui County's rate.",decision(intent='replace_plan',p=wire(plan(H('028'),[pov('HI-COUNTY-009-2024')]))),held)['status'],'propose')
        s25=decision(p=wire(plan(H('028'),[pov('HI-SENATE-025-2024')])));h25=decision(p=wire(plan(H('028'),[pov('HI-HOUSE-025-2024')])))
        for text in ('Compare senior poverty in House 28 with Senate district number 25.','Compare senior poverty in House 28 with district 25 in the Senate.'):
            self.assertEqual(self.convert(text,s25)['status'],'propose',text)
            self.refused('explicit_comparator_conflict',text,h25)
        self.recovered('unsupported','Predict no change in senior poverty for House 28.',decision(p=wire(plan(H('028'),[profile(['poverty_rate_65_plus'])]))),reason='unsupported_operation')
        self.assertEqual(self.convert('Profile senior poverty in House 28; I will predict nothing.',decision(p=wire(plan(H('028'),[profile(['poverty_rate_65_plus'])]))))['status'],'propose')

if __name__=='__main__':unittest.main()

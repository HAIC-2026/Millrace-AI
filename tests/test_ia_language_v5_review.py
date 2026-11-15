"""OX final-source-v5 review (v5 -> v6) regressions V5-1/V5-2: a bare trailing role noun never flips a primary;
removal/avoidance compare wording excludes its district; a negated removal verb fails closed. Injected decisions."""
import unittest
from public_app import load_core
from districtbrief.investigation import Investigation
import test_ia_language_repair as repair  # module import: its TestCases are not re-collected here
from test_ia_language_repair import H,plan,compare,wire,decision

S='HI-STATE-2024';MAUI='HI-COUNTY-009-2024'
def pov(geo,sid='s1'):return compare('poverty_rate_65_plus',geo,sid)

class V5ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    request=repair.LanguageRepairTests.request;convert=repair.LanguageRepairTests.convert
    refused=repair.LanguageRepairTests.refused

    def test_v5_1_bare_trailing_role_noun_never_flips_the_primary(self):
        held=plan(H('005','senate'),[pov(S)])
        for text,geo in (('Run the House 28 comparison against Maui County.',MAUI),('Show the House 28 benchmark versus Maui County.',MAUI),
                         ('Now do the House 28 comparison with the State.',S)):
            with self.subTest(text=text):
                out=self.convert(text,decision(intent='replace_plan',p=wire(plan(H('028'),[pov(geo)]))),held)
                self.assertEqual(out['normalized_plan']['district'],H('028'))
                self.refused('explicit_district_conflict',text,decision(intent='replace_plan',p=wire(plan(H('005','senate'),[pov('HI-HOUSE-028-2024')]))),held)
        # An actual role prefix still marks the comparator; a cue+article before the district still marks it.
        held28=plan(H('028'),[pov(S)])
        for text in ('Make House 30 the comparator.','Use House 30 as the baseline.','Use House 30 for comparison.'):
            self.assertEqual(self.convert(text,decision(intent='replace_plan',p=wire(plan(H('028'),[pov('HI-HOUSE-030-2024')]))),held28)['normalized_plan']['district'],H('028'),text)
        nat=decision(p=wire(plan(H('028'),[pov('HI-SENATE-025-2024')])));rev=decision(p=wire(plan(H('025','senate'),[pov('HI-HOUSE-028-2024')])))
        self.assertEqual(self.convert('Against a Senate 25 benchmark, measure House 28 senior poverty.',nat)['normalized_plan']['district'],H('028'))
        self.refused('explicit_district_conflict','Against a Senate 25 benchmark, measure House 28 senior poverty.',rev)

    def test_v5_2_removal_and_avoidance_wording_excludes_the_comparator(self):
        both=plan(H('028'),[pov(S,'s1'),pov('HI-HOUSE-030-2024','s2')])
        drop=decision(intent='replace_plan',p=wire(plan(H('028'),[pov(S,'s1')])));keep=decision(intent='replace_plan',p=wire(both))
        move=decision(intent='replace_plan',p=wire(plan(H('030'),[pov(S,'s1')])))
        for text in ('Remove the comparison with House 30.',"I don't want to compare with House 30.",'Avoid comparing with House 30.',
                     'There is no need to compare with House 30.','Skip the comparison with House 30.','Drop the comparison against House 30.'):
            with self.subTest(text=text):
                self.assertEqual([s['args']['comparison_geography'] for s in self.convert(text,drop,both)['normalized_plan']['steps']],[S])
                self.refused('explicit_district_conflict',text,keep,both);self.refused('explicit_district_conflict',text,move,both)

    def test_negated_removal_verb_cannot_be_proven_and_fails_closed(self):
        both=plan(H('028'),[pov(S,'s1'),pov('HI-HOUSE-030-2024','s2')])
        for text in ("Don't remove the comparison with House 30.",'Do not drop the comparison with House 30.',"Don't drop House 30.",
                     'Never exclude House 30.'):
            for d in (decision(intent='replace_plan',p=wire(both)),decision(intent='replace_plan',p=wire(plan(H('028'),[pov(S,'s1')])))):
                with self.subTest(text=text):self.refused('explicit_comparator_removal_ambiguous',text,d,both)
        # Plain negated compare forms are unchanged (OX3-2).
        self.assertEqual(self.convert("Don't compare with House 30 anymore.",decision(intent='replace_plan',p=wire(plan(H('028'),[pov(S,'s1')]))),both)['status'],'propose')

if __name__=='__main__':unittest.main()

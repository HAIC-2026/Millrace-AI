"""Named-county comparator correction: an explicitly named county comparator is never replaced by the State,
another county or another geography in an accepted proposal. Injected strict-function wire only."""
import unittest
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.ia_language import LanguageError
import test_ia_language_repair as repair  # module import: its TestCases are not re-collected here
from test_ia_language_repair import H,plan,compare,profile,wire,decision

HON,MAUI,KAUAI,HAW,KAL,STATE='HI-COUNTY-003-2024','HI-COUNTY-009-2024','HI-COUNTY-007-2024','HI-COUNTY-001-2024','HI-COUNTY-005-2024','HI-STATE-2024'
SP='poverty_rate_65_plus'

class CountyComparatorGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    request=repair.LanguageRepairTests.request;convert=repair.LanguageRepairTests.convert
    refused=repair.LanguageRepairTests.refused
    def rejected(self,*a):
        with self.assertRaises(LanguageError):self.convert(*a)
    def new(self,*geos,metric=SP,district=None):
        return decision(p=wire(plan(district or H('028'),[compare(metric,g,f's{i+1}') for i,g in enumerate(geos)])))
    def edit(self,held,*geos):
        steps=[profile([SP])]+[compare(SP,g,f's{i+2}') for i,g in enumerate(geos)]
        return decision(intent='replace_plan',p=wire(plan(H('028'),steps)))

    def test_named_county_accepted_and_never_replaced_on_new_plans(self):
        for text,geo in (('Compare senior poverty in House 28 with Honolulu County.',HON),
                         ('How does House 28 senior poverty compare to Maui County?',MAUI),
                         ("Senior poverty: House 28 versus Kauai County.",KAUAI),
                         ('Senior poverty in House 28 relative to the County of Hawaii.',HAW),
                         ('Compare senior poverty in House 28 against Honolulu County.',HON),
                         ('Using Maui County as the baseline, compare senior poverty in House 28.',MAUI)):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,self.new(geo))['status'],'propose')
                for wrong in (g for g in (STATE,HON,MAUI,KAUAI,HAW,KAL) if g!=geo):
                    self.rejected(text,self.new(wrong))
                self.refused('explicit_comparator_conflict',text,self.new(geo,STATE))  # the State was not asked for

    def test_listed_counties_and_state_are_all_required(self):
        text='Compare House 28 senior poverty with Honolulu County and the state.'
        self.assertEqual(self.convert(text,self.new(HON,STATE))['status'],'propose')
        self.refused('explicit_comparator_conflict',text,self.new(STATE))
        text='Compare House 28 senior poverty with Maui County, Kauai County and the State.'
        self.assertEqual(self.convert(text,self.new(MAUI,KAUAI,STATE))['status'],'propose')
        self.refused('explicit_comparator_conflict',text,self.new(MAUI,STATE))

    def test_held_comparator_does_not_stand_in_for_a_newly_named_county(self):
        held=plan(H('028'),[profile([SP]),compare(SP,MAUI,'s2')])
        for text in ('Compare it with Honolulu County instead.','Replace Maui County with Honolulu County.',
                     'Change the comparator to Honolulu County.','Swap the Maui County comparison for Honolulu County.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,self.edit(held,HON),held)['status'],'propose')
                self.rejected(text,self.edit(held,MAUI),held)
                self.rejected(text,self.edit(held,STATE),held)

    def test_context_mentions_and_negations_are_not_comparators(self):
        # A county named as context, not as a comparator, is not required.
        text='House 13 includes Kalawao County; compare its senior poverty with the state.'
        self.assertEqual(self.convert(text,self.new(STATE,district=H('013')))['status'],'propose')
        held=plan(H('028'),[profile([SP]),compare(SP,MAUI,'s2')])
        text="Don't compare with Maui County any more; compare with the state."
        self.assertEqual(self.convert(text,self.edit(held,STATE),held)['status'],'propose')
        self.rejected(text,self.edit(held,KAUAI),held)  # an unnamed county is never substituted

    def test_existing_state_and_district_comparator_refusals_are_kept(self):
        self.refused('explicit_comparator_unstated','Compare senior poverty in House 28 with the state.',self.new(HON))
        self.refused('explicit_comparator_unstated','Compare senior poverty in House 28 with a nearby county.',self.new(MAUI))
        self.refused('explicit_comparator_unstated','Compare senior poverty in House 28 to the statewide rate.',self.new(HON))
        self.refused('explicit_district_conflict','Compare senior poverty in House 28 with Maui County.',self.new(MAUI,district=H('029')))

    def test_ordinary_comparison_forms_and_county_aliases_require_the_named_county(self):
        # Ordinary comparative wording without a directed cue still names the comparator; aliases and the
        # okina/possessive forms resolve to the same county. The State, another county or nothing never replaces it.
        for text,geo in (('Compare senior poverty in House 28 with the City and County of Honolulu.',HON),
                         ('Compare senior poverty between House 28 and Maui County.',MAUI),
                         ('Compare House 28 and Maui County on senior poverty.',MAUI),
                         ('Show senior poverty for House 28 next to Maui County.',MAUI),
                         ('Put House 28 senior poverty alongside Kauaʻi County.',KAUAI),
                         ("Compare senior poverty in House 28 with Maui County's rate.",MAUI),
                         ('Compare senior poverty in House 28 with Hawaiʻi County.',HAW),
                         ('Senior poverty in House 28 vs. Maui County.',MAUI)):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,self.new(geo))['status'],'propose')
                for wrong in (STATE,HON,MAUI,KAUAI,HAW):
                    if wrong!=geo:self.rejected(text,self.new(wrong))
                self.rejected(text,self.new(geo,STATE))  # the State was not asked for
                self.rejected(text,decision(p=wire(plan(H('028'),[profile([SP])]))))  # the comparison cannot be dropped

    def test_explicitly_excluded_state_is_never_added(self):
        for text,geo in (('Compare senior poverty in House 28 with Honolulu County, not the state.',HON),
                         ('Compare senior poverty in House 28 with Maui County rather than the state.',MAUI),
                         ('Instead of the state, compare senior poverty in House 28 with Kauai County.',KAUAI),
                         ('Compare senior poverty in House 28 with Maui County, excluding the statewide rate.',MAUI)):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,self.new(geo))['status'],'propose')
                self.rejected(text,self.new(geo,STATE));self.rejected(text,self.new(STATE))
        # Without a county: an excluded State is still never added; a named district comparator is kept.
        text='Compare senior poverty in House 28 with House 30, not the state.'
        self.assertEqual(self.convert(text,self.new('HI-HOUSE-030-2024'))['status'],'propose')
        self.rejected(text,self.new('HI-HOUSE-030-2024',STATE))
        # A positively named State next to a named county is still allowed.
        self.assertEqual(self.convert('Compare House 28 senior poverty with Maui County and the state.',self.new(MAUI,STATE))['status'],'propose')

    def test_context_only_county_and_non_comparative_mentions_keep_working(self):
        for text,district in (('House 13 includes Kalawao County; compare its senior poverty with the state.',H('013')),
                              ('House 28 is in Honolulu County. Compare its senior poverty with the state.',H('028')),
                              ('For House 28, located in the City and County of Honolulu, compare senior poverty to the state.',H('028'))):
            with self.subTest(text=text):self.assertEqual(self.convert(text,self.new(STATE,district=district))['status'],'propose')
        text='Show senior poverty for House 28 in Honolulu County.'
        self.assertEqual(self.convert(text,decision(p=wire(plan(H('028'),[profile([SP])]))))['status'],'propose')
        self.rejected(text,self.new(MAUI))  # an unnamed county is still never invented

    def test_plural_and_shared_noun_county_lists_are_all_required(self):
        for text,geos in (('Compare senior poverty in House 28 with Maui and Kauai counties.',(MAUI,KAUAI)),
                          ('Compare senior poverty in House 28 with Maui, Kauaʻi and Hawaiʻi counties.',(MAUI,KAUAI,HAW)),
                          ("Compare House 28 senior poverty with Honolulu or Maui counties' rates.",(HON,MAUI))):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,self.new(*geos))['status'],'propose')
                self.rejected(text,self.new(STATE));self.rejected(text,self.new(*geos[:-1]));self.rejected(text,self.new(*geos,STATE))
        # Context-only lists are not comparators; an unnamed county is still never invented.
        text='House 13 includes Maui and Kalawao counties; compare its senior poverty with the state.'
        self.assertEqual(self.convert(text,self.new(STATE,district=H('013')))['status'],'propose')
        self.rejected('Compare senior poverty in House 28 with Maui and Kauai counties.',self.new(MAUI,HON))

    def test_parenthetical_district_location_is_context(self):
        text='Compare senior poverty in House 13 (Maui County) with the state.'
        self.assertEqual(self.convert(text,self.new(STATE,district=H('013')))['status'],'propose')
        self.rejected(text,self.new(MAUI,district=H('013')))  # the State was asked for and is not dropped
        text='Compare senior poverty in House 13 with Maui County.'  # an explicit comparator is not location context
        self.assertEqual(self.convert(text,self.new(MAUI,district=H('013')))['status'],'propose')
        self.rejected(text,self.new(STATE,district=H('013')))

    def test_not_just_the_state_adds_the_state_and_genuine_exclusion_still_works(self):
        for text in ('Compare senior poverty in House 28 with Maui County and not just the state.',
                     'Compare senior poverty in House 28 with Maui County, not only the State.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,self.new(MAUI,STATE))['status'],'propose')
                self.rejected(text,self.new(MAUI));self.rejected(text,self.new(STATE))
        text='Compare senior poverty in House 28 with Maui County, not the state.'
        self.assertEqual(self.convert(text,self.new(MAUI))['status'],'propose');self.rejected(text,self.new(MAUI,STATE))
        # A State named as a comparator is never silently dropped.
        self.rejected('Compare House 28 senior poverty with Honolulu County and the state.',self.new(HON))

    def test_removed_state_is_enforced_even_when_held(self):
        held=plan(H('028'),[profile([SP]),compare(SP,MAUI,'s2'),compare(SP,STATE,'s3')])
        for text in ('Drop the state comparison.','Remove the State comparison and keep Maui County.','Compare with Maui County, not the state.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,self.edit(held,MAUI),held)['status'],'propose')
                self.rejected(text,self.edit(held,MAUI,STATE),held)
        # Keeping or adding the State still works when the State is not removed.
        self.assertEqual(self.convert('Add the state comparison too.',self.edit(plan(H('028'),[profile([SP]),compare(SP,MAUI,'s2')]),MAUI,STATE),
                                      plan(H('028'),[profile([SP]),compare(SP,MAUI,'s2')]))['status'],'propose')

    def test_statewide_service_area_is_not_a_state_comparator(self):
        d=decision(p=wire(plan(H('028'),[compare(SP,MAUI)],svc='statewide')))
        self.assertEqual(self.convert('Compare senior poverty in House 28 with Maui County and set the service area to statewide.',d)['status'],'propose')

    def test_list_head_and_shared_singular_county_lists(self):
        for text,geos in (('Compare senior poverty in House 28 with the counties of Maui and Kauai.',(MAUI,KAUAI)),
                          ('Compare senior poverty in House 28 with the counties of Maui, Kauaʻi and Hawaiʻi.',(MAUI,KAUAI,HAW)),
                          ('Compare senior poverty in House 28 with Maui and Kauai County.',(MAUI,KAUAI)),
                          ("Compare senior poverty in House 28 with Maui or Kauai County's rate.",(MAUI,KAUAI))):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,self.new(*geos))['status'],'propose')
                self.rejected(text,self.new(STATE));self.rejected(text,self.new(*geos[1:]));self.rejected(text,self.new(*geos[:-1]))
        # Without a county word an island or the State of Hawaii is not a county; a plural needs two names.
        for text in ('Compare senior poverty in House 28 with other Hawaii counties.','Compare senior poverty in House 28 with the State of Hawaii.'):
            with self.subTest(text=text):self.rejected(text,self.new(HAW))
        self.rejected('Compare senior poverty in House 28 with Maui.',self.new(MAUI))

    def test_statewide_service_area_never_adds_a_state_comparator(self):
        for text,geo in (('Compare House 28 senior poverty with Maui County for the statewide service area.',MAUI),
                         ('Compare House 28 senior poverty with House 30 for the statewide service area.','HI-HOUSE-030-2024')):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text,self.new(geo))['status'],'propose')
                self.rejected(text,self.new(geo,STATE))
        # An explicit State comparison next to a statewide service area is still allowed and required.
        text='Compare House 28 senior poverty with Maui County and the state for the statewide service area.'
        self.assertEqual(self.convert(text,self.new(MAUI,STATE))['status'],'propose');self.rejected(text,self.new(MAUI))

if __name__=='__main__':unittest.main()

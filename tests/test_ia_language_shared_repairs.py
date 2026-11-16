"""V3 shared guard repairs (same engine for every model profile). Public synthetic wordings only; injected strict wire.
1 State plus other comparators; 2 one held rule for program context; 3 provider inheritance labels are not authority;
4 typed comparator choices instead of guessing (bare island, bare district number) and the coextensive Big Island."""
import copy
import unittest
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.interpret import food_assistance_recipe, recipe
from districtbrief.ia_language import LanguageError
import test_ia_language_repair as repair
from test_ia_language_repair import H,plan,compare,profile,wire,decision

HON,MAUI,KAUAI,HAW,STATE='HI-COUNTY-003-2024','HI-COUNTY-009-2024','HI-COUNTY-007-2024','HI-COUNTY-001-2024','HI-STATE-2024'
SP='poverty_rate_65_plus'
def evidence(programs,sid='s9'):return {'step_id':sid,'operation':'program_evidence','args':{'program_ids':programs}}

class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.i=Investigation(load_core())
    request=repair.LanguageRepairTests.request;convert=repair.LanguageRepairTests.convert;refused=repair.LanguageRepairTests.refused
    def rejected(self,*a,**kw):
        with self.assertRaises(LanguageError):self.convert(*a,**kw)
    def new(self,*geos,district=None,metric=SP):
        return decision(p=wire(plan(district or H('028'),[compare(metric,g,f's{i+1}') for i,g in enumerate(geos)])))
    def accepted(self,*a,**kw):
        out=self.convert(*a,**kw);self.assertEqual(out['status'],'propose',out.get('recovered_from'));return out

class StateWithOtherComparatorsTests(Base):
    def test_state_plus_named_counties_and_districts_any_order_and_geography(self):
        cases=(('Compare senior poverty in House 28 with Maui County and the State.',H('028'),(MAUI,STATE)),
               ('Compare senior poverty in House 28 with the State and Maui County.',H('028'),(STATE,MAUI)),
               ('Senior poverty in Senate 5 versus the State, Honolulu County and Kauai County.',H('005','senate'),(STATE,HON,KAUAI)),
               ('How does House 13 senior poverty compare with House 12 and the State?',H('013'),('HI-HOUSE-012-2024',STATE)),
               ('Senior poverty in House 13 versus the State and versus House 12.',H('013'),(STATE,'HI-HOUSE-012-2024')),
               ('Compare Senate 25 senior poverty against Hawaii County, then against the State.',H('025','senate'),(HAW,STATE)),
               ('Compare senior poverty in House 7 to the state as well as the County of Maui.',H('007'),(MAUI,STATE)))
        for text,district,geos in cases:
            with self.subTest(text=text):
                self.accepted(text,self.new(*geos,district=district))
                # Every named comparator stays required, and nothing unnamed may be added.
                self.rejected(text,self.new(*geos[1:],district=district))
                self.rejected(text,self.new(*geos[:-1],district=district))
                self.rejected(text,self.new(*geos,'HI-COUNTY-005-2024',district=district))
    def test_direction_negation_replacement_and_service_area_still_hold(self):
        # Direction: the primary is still the unmarked district; comparators carry the cue.
        text='Compare House 12 senior poverty with House 28 and the State.'
        self.accepted(text,self.new('HI-HOUSE-028-2024',STATE,district=H('012')))
        self.rejected(text,self.new('HI-HOUSE-012-2024',STATE,district=H('028')))
        # Negation/removal of a county or the State is never compared, even beside a State comparison.
        for text,good,bad in (('Compare senior poverty in House 28 with the State, not Maui County.',(STATE,),(STATE,MAUI)),
                              ('Compare senior poverty in House 28 with Kauai County, not the State.',(KAUAI,),(KAUAI,STATE)),
                              ('Compare senior poverty in House 28 with the State but exclude Honolulu County.',(STATE,),(STATE,HON))):
            with self.subTest(text=text):
                self.accepted(text,self.new(*good));self.rejected(text,self.new(*bad))
        held=plan(H('028'),[compare(SP,MAUI)])
        for text in ('Replace Maui County with the State.','Compare with the State instead of Maui County.'):
            with self.subTest(text=text):
                self.accepted(text,decision(intent='replace_plan',p=wire(plan(H('028'),[compare(SP,STATE,'s2')]))),held)
                self.rejected(text,decision(intent='replace_plan',p=wire(plan(H('028'),[compare(SP,MAUI),compare(SP,STATE,'s2')]))),held)
        # Statewide service-area wording never adds a State comparator.
        self.rejected('Compare House 28 senior poverty with Maui County for the statewide service area.',self.new(MAUI,STATE))
    def test_held_comparator_kept_only_with_additive_wording(self):
        held=plan(H('028'),[compare(SP,MAUI)]);both=decision(intent='replace_plan',p=wire(plan(H('028'),[compare(SP,MAUI),compare(SP,STATE,'s2')])))
        for text in ('Also compare with the State.','Add the State as well.','Keep Maui County and also compare with the State.'):
            with self.subTest(text=text):self.accepted(text,both,held)
        # A bare restated State comparison never silently keeps an old comparator (same outcome as before V3).
        self.refused('explicit_comparator_conflict','Compare with the State.',both,held)
        self.accepted('Compare with the State.',decision(intent='replace_plan',p=wire(plan(H('028'),[compare(SP,STATE,'s2')]))),held)
    def test_coordinated_peer_districts_after_a_directed_comparator(self):
        H12,H27='HI-HOUSE-012-2024','HI-HOUSE-027-2024'
        for text,geos,district in (('How does House 13 senior poverty compare with the State and House 12?',(STATE,H12),H('013')),
                                   ('Compare senior poverty in Senate 5 against Maui County and House 27.',(MAUI,H27),H('005','senate')),
                                   ('Compare House 13 senior poverty with House 12 and House 27 and the State.',(H12,H27,STATE),H('013')),
                                   ('Compare senior poverty in House 13 versus the State or House 12.',(STATE,H12),H('013'))):
            with self.subTest(text=text):
                self.accepted(text,self.new(*geos,district=district))
                self.rejected(text,self.new(*[g for g in geos if g.startswith('HI-COUNTY') or g==STATE],district=district))  # peer required
                self.rejected(text,self.new(*geos,district=H('012')))  # the explicit primary never moves to the peer
        held=plan(H('013'),[compare(SP,STATE)])
        self.accepted('Also compare with the State and House 12.',decision(intent='replace_plan',p=wire(plan(H('013'),[compare(SP,STATE),compare(SP,H12,'s2')]))),held)
    def test_peer_rule_never_guesses_new_primaries_negation_or_navigation(self):
        H12='HI-HOUSE-012-2024'
        # A district opening its own comparison clause is a second primary: ambiguous, never folded into one plan.
        self.refused('explicit_district_ambiguous','Compare House 13 with the State, and House 12 with Maui County.',self.new(STATE,H12,MAUI,district=H('013')))
        # Negated peers are excluded; navigation names a new primary; undirected lists stay ambiguous.
        text='Compare House 13 senior poverty with the State and not House 12.'
        self.accepted(text,self.new(STATE,district=H('013')));self.rejected(text,self.new(STATE,H12,district=H('013')))
        self.rejected('Compare House 13 senior poverty with the State and switch to House 12.',self.new(STATE,H12,district=H('013')))
        self.refused('explicit_district_ambiguous','Profile senior poverty in House 13 and House 12.',self.new(H12,district=H('013')))
        self.refused('explicit_district_ambiguous','Show the State and House 12 next to House 13.',self.new(STATE,H12,district=H('013')))
        # A bare comma after a comparator opens the main clause; it never makes the next district a peer.
        self.accepted('Compare to Senate 25, House 28 senior poverty.',self.new('HI-SENATE-025-2024',district=H('028')))
        # A removed State never makes the next district a peer.
        self.rejected('Compare House 13 senior poverty with Maui County, remove the State and House 12.',self.new(MAUI,H12,district=H('013')))
    def test_unnamed_comparators_beside_the_state_are_still_refused(self):
        for geo in (HON,'HI-HOUSE-027-2024','HI-SENATE-014-2024'):
            with self.subTest(geo=geo):self.rejected('Compare senior poverty in House 28 with the State.',self.new(STATE,geo))

class HeldProgramContextTests(Base):
    def test_unconfirmed_recipe_draft_comparison_edit_reads_the_held_draft(self):
        for build,text in ((recipe,'Also compare senior poverty with Maui County.'),(food_assistance_recipe,'Add a comparison of overall poverty with Honolulu County.')):
            draft=build(H('028'));edited=copy.deepcopy(draft);metric='poverty_rate_65_plus' if build is recipe else 'poverty_rate_all_people'
            edited['steps'].append(compare(metric,MAUI if build is recipe else HON,'s9'))
            with self.subTest(recipe=draft['issue_id']):
                out=self.accepted(text,decision(intent='replace_plan',p=wire(edited)),None,draft)
                self.assertEqual(out['inherited_fields'],[])  # draft-only context is never labelled inherited
                # A NEW unrequested program beside the held draft is still refused.
                extra=copy.deepcopy(edited);extra['steps'].append(evidence(['medquest_hi'],'s10'))
                self.rejected(text,decision(intent='replace_plan',p=wire(extra)),None,draft)
    def test_confirmed_still_wins_over_a_conflicting_draft(self):
        confirmed=plan(H('028'),[compare(SP,STATE)]);draft=recipe(H('028'))
        edited=copy.deepcopy(draft);edited['steps'].append(compare(SP,MAUI,'s9'))
        out=self.convert('Also compare senior poverty with Maui County.',decision(intent='replace_plan',p=wire(edited)),confirmed,draft)
        self.assertEqual((out['status'],out['clarify_field']),('clarify','control_conflict'))  # never silently prefers the draft
    def test_food_stamps_names_snap_only(self):
        snap=plan(H('028'),[evidence(['snap_hi'],'s1')])
        for text in ('Show food stamps evidence for House 28.','Show food stamp program evidence for House 28.'):
            with self.subTest(text=text):self.accepted(text,decision(p=wire(snap)))
        self.refused('ungrounded_program','Show food stamps evidence for House 28.',decision(p=wire(plan(H('028'),[evidence(['snap_hi','wic_hi'],'s1')]))))
        self.refused('ungrounded_program','Show food stamps evidence for House 28.',decision(p=wire(plan(H('028'),[evidence(['wic_hi'],'s1')]))))
        self.refused('negated_program','Show program evidence for House 28, not food stamps.',decision(p=wire(snap)))

class ProviderInheritanceLabelTests(Base):
    def test_correct_plan_with_wrong_metadata_uses_server_derivation(self):
        held=plan(H('028'),[compare(SP,STATE)])
        moved=copy.deepcopy(held);moved['district']=H('025','senate')
        for labels in (['district'],['district','steps','focus'],['map_session'],[]):
            with self.subTest(labels=labels):
                out=self.accepted('Same comparison for Senate 25.',decision(intent='replace_plan',p=wire(moved),inherited_fields=labels),held)
                self.assertEqual(sorted(out['inherited_fields']),['issue_id','map_session','service_area_id','steps'])
                self.assertEqual([d['field'] for d in out['typed_diff']],['district'])
        out=self.accepted('Profile median age in House 28.',decision(p=wire(plan()),inherited_fields=['district','focus']))
        self.assertEqual(out['inherited_fields'],[])  # no confirmed context: nothing is inherited, whatever the labels say
    def test_wrong_plan_with_plausible_metadata_is_still_refused(self):
        held=plan(H('028'),[compare(SP,STATE)])
        silently_moved=copy.deepcopy(held);silently_moved['district']=H('029')
        self.refused('explicit_district_unstated_change','Also show the comparison again.',decision(intent='replace_plan',p=wire(silently_moved),inherited_fields=['steps']),held)
        renamed=wire(held);renamed['steps']=[dict(renamed['steps'][0],step_id='s7')]
        self.refused('changed_unchanged_step_id','Compare senior poverty with the State.',decision(intent='replace_plan',p=renamed,inherited_fields=['district','steps']),held)
        self.refused('explicit_comparator_unstated','Compare senior poverty in House 28.',self.new(HON),)
        # Non-proposal and source-inspection wire constraints are unchanged: labels there are still refused.
        self.refused('inapplicable_provider_fields','Forecast House 28.',decision('unsupported','none',reason_code='unsupported_operation',inherited_fields=['district']))

class TypedComparatorChoiceTests(Base):
    def test_big_island_is_hawaii_county_only_as_a_comparator(self):
        for text in ('Compare senior poverty in House 28 with the Big Island.','Senior poverty in Senate 1 versus Hawaii Island.',
                     'Compare senior poverty in House 28 with Maui County and the Big Island.'):
            with self.subTest(text=text):
                geos=(MAUI,HAW) if 'Maui' in text else (HAW,)
                district=H('001','senate') if 'Senate 1' in text else H('028')
                self.accepted(text,self.new(*geos,district=district))
                self.rejected(text,self.new(*[g for g in geos if g!=HAW],STATE,district=district))
        self.rejected('Compare senior poverty in House 28 with the State, not the Big Island.',self.new(STATE,HAW))
        self.accepted('Compare senior poverty in House 28 with the State, not the Big Island.',self.new(STATE))
        # As a service area it is not a comparator, and it never authorizes a county comparison.
        self.rejected('Set the service area to the Big Island and profile median age in House 28.',self.new(HAW))
    def test_bare_island_and_bare_district_comparators_get_relevant_choices(self):
        for text,choices in (('Compare senior poverty in House 28 with Kauai.',[KAUAI]),('Senior poverty in House 28 versus Oahu.',[HON])):
            for geos in ((STATE,),(choices[0],),()):
                with self.subTest(text=text,geos=geos):
                    out=self.convert(text,self.new(*geos))
                    self.assertEqual((out['status'],out['clarify_field'],[c['value'] for c in out['choices']]),('clarify','comparator',choices))
        for geos in ((STATE,),()):
            with self.subTest(dropped=geos):
                out=self.convert('Compare senior poverty in House 28 against district 14.',self.new(*geos))
                self.assertEqual((out['status'],[c['value'] for c in out['choices']]),('clarify',['HI-HOUSE-014-2024','HI-SENATE-014-2024']))
        out=self.convert('Compare senior poverty in House 28 against district 27.',self.new())  # Senate has 25 districts
        self.assertEqual([c['value'] for c in out['choices']],['HI-HOUSE-027-2024'])
        # Named chambers and county words are unchanged: no clarification.
        self.accepted('Compare senior poverty in House 28 against House 27.',self.new('HI-HOUSE-027-2024'))
        self.accepted('Compare senior poverty in House 28 with Kauai County.',self.new(KAUAI))
        # "Hawaii" alone is never offered or read as a county (it may mean the State).
        out=self.convert('Compare senior poverty in House 28 with the State of Hawaii.',self.new(STATE));self.assertEqual(out['status'],'propose')
        self.rejected('Compare senior poverty in House 28 with Hawaii.',self.new(HAW))

if __name__=='__main__':unittest.main()

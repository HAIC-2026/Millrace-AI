"""SNAP participation-gap questions: no count, a typed offer of the checked SNAP outreach recipe for one named district.

Offline only. The job test injects a production-shaped strict-function provider transport and a temporary ledger; no
credential, network or paid call is used. The offer is value-free: it names a program, recipe and district and never a
figure, plan or model field."""
import copy
import json
import re
import tempfile
import unittest
import uuid
from public_app import Application, load_core
from districtbrief.claim_binding import plan_hash
from districtbrief.investigation import Investigation
from districtbrief.ia_language import EMPTY_PLAN, SCHEMA_VERSION, LanguageError, convert_decision, coordinated_gap_asked, prepare_request, snap_gap_offer, wire_plan
from districtbrief.ia_language_jobs import LanguageService
from districtbrief.ia_language_provider import OpenAIProvider
from districtbrief.interpret import food_assistance_recipe, recipe
from language_funding_fixture import ledger_fixture, usage

COLD = 'How many House District 28 residents qualify for SNAP but aren’t enrolled? Give me something I can take into a meeting.'
H28 = {'state_fips': '15', 'chamber': 'house', 'code': '028', 'boundary_session': 2024}
OFFER_28 = {'kind': 'snap_participation_gap', 'program_id': 'snap_hi', 'issue_id': 'food_assistance_outreach', 'district': H28}
GAP_CHECK = 'Ask DHS BESSD for SNAP enrollment and eligible-population data for House 028 or a matching area.'


def decision(status, intent='none', plan=None, reason=''):
    return {'status': status, 'intent': intent, 'plan': copy.deepcopy(plan if plan is not None else EMPTY_PLAN), 'focus_alias': '',
            'clarify_field': '', 'clarify_choices': [], 'reason_code': reason, 'inherited_fields': []}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.i = Investigation(load_core())
        # Every SNAP participation figure the packet holds (statewide, county); none may appear in an offer.
        with open('runtime-packet/data/participation/observations.json', encoding='utf-8') as f:
            rows = json.load(f)
        cls.figures = {f"{r['value']:,}" for r in rows if r['program_id'] == 'snap_hi' and r['value'] is not None} | \
                      {str(r['value']) for r in rows if r['program_id'] == 'snap_hi' and r['value'] is not None}

    def request(self, text, held=None, draft='same'):
        held = recipe(H28) if held is None else held
        draft = copy.deepcopy(held) if draft == 'same' else copy.deepcopy(draft)
        return {'schema_version': SCHEMA_VERSION, 'request_id': str(uuid.uuid4()), 'utterance': text, 'context': {
            'case_id': str(uuid.uuid4()), 'branch_id': str(uuid.uuid4()), 'revision': 1, 'snapshot_id': self.i.snapshot_id,
            'operation_version': 'ia-core/1', 'recipe_version': 'aging_at_home/1', 'confirmed_plan': copy.deepcopy(held),
            'draft_plan': draft, 'focused_step_id': None, 'selected_claim_refs': []}}

    def prepared(self, text, **kw):
        return prepare_request(self.request(text, **kw), self.i, 's')

    def assert_value_free(self, out):
        blob = json.dumps(out.get('participation_gap'), ensure_ascii=False)
        for figure in self.figures:
            self.assertNotIn(figure, blob)
        self.assertIsNone(out['normalized_plan'])
        self.assertEqual((out['typed_diff'], out['choices'], out['source_inspection_refs']), ([], [], []))


class DetectorTests(Base):
    def test_exact_cold_input_offers_house_28_outreach_on_either_unsupported_reason(self):
        p = self.prepared(COLD)
        self.assertEqual(snap_gap_offer(p), OFFER_28)
        for reason in ('unavailable_evidence', 'unsupported_operation'):
            with self.subTest(reason=reason):
                out = convert_decision(p, decision('unsupported', reason=reason), self.i.core)
                self.assertEqual((out['status'], out['reason_code'], out['participation_gap']), ('unsupported', reason, OFFER_28))
                self.assert_value_free(out)

    def test_server_recovery_of_a_model_proposal_carries_the_offer_but_no_plan(self):
        # The model proposes the SNAP recipe; the local guard refuses the eligibility request as unsupported.
        p = self.prepared(COLD)
        wire = wire_plan(food_assistance_recipe(H28)); wire['map_session'] = 0
        out = convert_decision(p, decision('propose', 'create_plan', wire), self.i.core)
        self.assertEqual((out['status'], out['reason_code'], out.get('recovered_from')), ('unsupported', 'unsupported_operation', 'unsupported_explicit_constraint'))
        self.assertEqual(out['participation_gap'], OFFER_28)
        self.assert_value_free(out)

    def test_equivalent_gap_wordings_offer_the_named_district(self):
        for text, district in (('Show the SNAP participation gap in House 28.', H28),
                               ('How many HD 28 residents are eligible for SNAP but not receiving it?', H28),
                               ('Eligible non-participants for food stamps in house district 28?', H28),
                               ('How many Senate 12 residents qualify for SNAP but are not enrolled?', dict(H28, chamber='senate', code='012'))):
            with self.subTest(text=text):
                self.assertEqual(snap_gap_offer(self.prepared(text))['district'], district)

    def test_generic_or_unrelated_refusals_get_no_offer(self):
        for text in ('Forecast senior population in House 28.', 'What causes senior poverty in House 28?',
                     'How many residents in House 28 are eligible for SNAP?',          # eligibility only, not a gap
                     'List the names of residents on SNAP in House 28.',
                     'How many House 28 residents qualify for Medicaid but aren’t enrolled?',
                     'How many House 28 residents qualify for SNAP or WIC but aren’t enrolled?',
                     'How many House 28 kupuna qualify for Kupuna Care but are not enrolled?',
                     'How many House 28 residents qualify for benefit programs but aren’t enrolled?',
                     'Not SNAP: how many House 28 residents qualify for housing help but are not enrolled?'):
            with self.subTest(text=text):
                p = self.prepared(text)
                self.assertIsNone(snap_gap_offer(p))
                out = convert_decision(p, decision('unsupported', reason='unsupported_operation'), self.i.core)
                self.assertNotIn('participation_gap', out)

    def test_different_or_ambiguous_geography_gets_no_offer(self):
        for text in ('How many residents qualify for SNAP but aren’t enrolled?',                     # no district
                     'How many residents in district 28 qualify for SNAP but aren’t enrolled?',      # no chamber
                     'How many House 28 and House 5 residents qualify for SNAP but aren’t enrolled?',
                     'How many Senate 28 residents qualify for SNAP but aren’t enrolled?',          # outside the chamber
                     'How many House 52 residents qualify for SNAP but aren’t enrolled?',
                     'How many residents of council district 5 qualify for SNAP but aren’t enrolled?',
                     'In congressional district 1 and House 28, who qualifies for SNAP but is not enrolled?',
                     'How many House 28 residents in Maui County qualify for SNAP but aren’t enrolled?',
                     'How many House 28 residents qualify for SNAP but aren’t enrolled, compared with the State?',
                     'How many House 28 residents qualify for SNAP but aren’t enrolled versus House 5?',
                     'Not House 28: how many residents qualify for SNAP but aren’t enrolled?',
                     'On the 2024 map, how many House 28 residents qualify for SNAP but aren’t enrolled?'):
            with self.subTest(text=text):
                self.assertIsNone(snap_gap_offer(self.prepared(text)))

    def test_snap_bound_paraphrases_offer_and_keep_the_typed_refusal(self):
        # Eligibility and enrollment words bind to SNAP in a fixed form; the refusal keeps its own reason code.
        for text in ('How many people in House 28 are eligible for SNAP but not signed up?',
                     'How many SNAP-eligible residents in House 28 are not enrolled?',
                     'How many SNAP-eligible households in House 28 aren\u2019t receiving it?',
                     'In House 28, how many households qualify for food stamps but don\u2019t get them?',
                     'House 28: residents eligible for SNAP who are not enrolled in SNAP.',
                     'What is the participation gap in SNAP for House 28?',
                     'House district 28 residents who qualify for SNAP benefits and are not receiving them?'):
            with self.subTest(text=text):
                p = self.prepared(text)
                for reason in ('unsupported_operation', 'unavailable_evidence'):
                    out = convert_decision(p, decision('unsupported', reason=reason), self.i.core)
                    self.assertEqual((out['status'], out['reason_code'], out['participation_gap']), ('unsupported', reason, OFFER_28))
                    self.assert_value_free(out)

    def test_enrollment_or_eligibility_about_another_program_gets_the_generic_refusal(self):
        for text in ('In House 28, how many SNAP recipients are eligible for Medicare but not enrolled?',
                     'How many SNAP recipients in House 28 qualify for Medicare but aren\u2019t enrolled?',
                     'How many House 28 residents qualify for SNAP but aren\u2019t enrolled in Medicaid?',
                     'How many House 28 residents qualify for SNAP but aren\u2019t enrolled in Medicare?',
                     'How many House 28 residents qualify for SNAP and Medicare but aren\u2019t enrolled?',
                     'How many House 28 SNAP recipients qualify for housing aid but aren\u2019t enrolled?',
                     'How many House 28 residents receive SNAP but aren\u2019t eligible?',
                     'How many House 28 residents are not eligible for SNAP but enrolled?',
                     'How many House 28 residents are eligible for SNAP but not enrolled in school?'):
            with self.subTest(text=text):
                p = self.prepared(text)
                self.assertIsNone(snap_gap_offer(p))
                out = convert_decision(p, decision('unsupported', reason='unsupported_operation'), self.i.core)
                self.assertEqual((out['status'], out['reason_code']), ('unsupported', 'unsupported_operation'))
                self.assertNotIn('participation_gap', out)

    def test_coordinated_ranged_or_extra_chamber_references_are_not_one_district(self):
        for text in ('How many House 28 or 29 residents qualify for SNAP but aren\u2019t enrolled?',
                     'How many House 28 and 29 residents qualify for SNAP but aren\u2019t enrolled?',
                     'How many House 28, 29 residents qualify for SNAP but aren\u2019t enrolled?',
                     'How many House 28-30 residents qualify for SNAP but aren\u2019t enrolled?',
                     'How many House 28 to 30 residents qualify for SNAP but aren\u2019t enrolled?',
                     'How many residents in House districts 28 through 30 qualify for SNAP but aren\u2019t enrolled?',
                     'How many 27 or House 28 residents qualify for SNAP but aren\u2019t enrolled?',
                     'How many Houses 28 residents qualify for SNAP but aren\u2019t enrolled?',
                     'For House 28 and the Senate, how many qualify for SNAP but aren\u2019t enrolled?',
                     'How many House 28 or district 29 residents qualify for SNAP but aren\u2019t enrolled?',
                     'How many HD 28 or HD 29 residents qualify for SNAP but aren\u2019t enrolled?'):
            with self.subTest(text=text):
                p = self.prepared(text)
                self.assertIsNone(snap_gap_offer(p))
                self.assertNotIn('participation_gap', convert_decision(p, decision('unsupported', reason='unavailable_evidence'), self.i.core))

    def test_gap_synonyms_refuse_a_valid_substitute_plan_with_the_typed_recovery(self):
        # A strict-wire, executable SNAP recipe proposal is replaced by the fixed unsupported recovery plus the offer.
        wire = wire_plan(food_assistance_recipe(H28)); wire['map_session'] = 0
        for text in ('What is the SNAP enrollment gap in House 28?', 'Give me a brief on the SNAP take-up gap for House 28.'):
            for intent in ('create_plan', 'replace_plan'):
                with self.subTest(text=text, intent=intent):
                    p = self.prepared(text)
                    out = convert_decision(p, decision('propose', intent, wire), self.i.core)
                    self.assertEqual((out['status'], out['intent'], out['reason_code'], out['recovered_from'], out['recovery_category']),
                                     ('unsupported', 'none', 'unsupported_operation', 'unsupported_explicit_constraint', 'unsupported_inference'))
                    self.assertEqual(out['participation_gap'], OFFER_28)
                    self.assert_value_free(out)
                    # A model refusal keeps its own reason code; no recovery attribution is added.
                    own = convert_decision(p, decision('unsupported', reason='unavailable_evidence'), self.i.core)
                    self.assertEqual((own['reason_code'], own.get('recovered_from'), own['participation_gap']), ('unavailable_evidence', None, OFFER_28))

    def test_unqualified_requests_keep_their_proposal_clarification_or_uncertain_outcome(self):
        wire = wire_plan(food_assistance_recipe(H28)); wire['map_session'] = 0
        # Ordinary SNAP outreach and a gap about another program stay proposals: no SNAP gap is asked.
        for text in ('Show SNAP outreach for House 28.', 'Show SNAP program evidence and outreach for House 28.'):
            with self.subTest(text=text):
                out = convert_decision(self.prepared(text), decision('propose', 'create_plan', wire), self.i.core)
                self.assertEqual(out['status'], 'propose')
                self.assertNotIn('participation_gap', out)
        # A clear SNAP gap about an ambiguous district never accepts a substitute plan for one arbitrary district: the
        # same generic unsupported recovery, with no outreach offer because no single district is established.
        for text in ('Give me a brief on the SNAP take-up gap for House 28 or 29.', 'What is the SNAP enrollment gap in House 28-30?',
                     'How many House 28 and 29 residents qualify for SNAP but aren\u2019t enrolled?'):
            with self.subTest(text=text):
                out = convert_decision(self.prepared(text), decision('propose', 'create_plan', wire), self.i.core)
                self.assertEqual((out['status'], out['intent'], out['reason_code'], out['normalized_plan'], out['recovered_from']),
                                 ('unsupported', 'none', 'unsupported_operation', None, 'unsupported_explicit_constraint'))
                self.assertNotIn('participation_gap', out)
        p = self.prepared('What is the SNAP enrollment gap in House 28?')
        out = convert_decision(p, decision('uncertain', reason='uncertain_interpretation'), self.i.core)
        self.assertEqual((out['status'], out['reason_code']), ('uncertain', 'uncertain_interpretation'))
        self.assertNotIn('participation_gap', out)
        # An invalid proposal is still refused as before (uncertain in the job), never recovered into an offer.
        bad = copy.deepcopy(wire); bad['issue_id'] = 'not_an_issue'
        with self.assertRaises(LanguageError):
            convert_decision(p, decision('propose', 'create_plan', bad), self.i.core)

    def test_plain_district_wording_keeps_the_offer(self):
        for text in ('How many residents of House 28 qualify for SNAP but aren\u2019t enrolled?',
                     'How many House 28 residents qualify for SNAP but aren\u2019t enrolled? I need it for a meeting.',
                     'In House 28, how many households qualify for food stamps but don\u2019t get them?',
                     'What is the SNAP enrollment gap in House 28?', 'Give me a brief on the SNAP take-up gap for House 28.'):
            with self.subTest(text=text):
                self.assertEqual(snap_gap_offer(self.prepared(text)), OFFER_28)

    def test_qualified_related_wider_finer_island_or_historical_geography_gets_no_offer_and_no_plan(self):
        # The gap is still refused (no substitute plan for a broader or different area); only the House 28 offer is withheld.
        wire = wire_plan(food_assistance_recipe(H28)); wire['map_session'] = 0
        q = 'qualify for SNAP but aren\u2019t enrolled?'
        texts = [f'How many residents {w} House 28 {q}' for w in ('near', 'around', 'outside', 'nearby', 'bordering')] + [
            f'How many residents in districts neighboring House 28 {q}', f'How many residents in House 28 and adjacent districts {q}',
            f'How many residents in House 28 and the surrounding area {q}', f'How many residents in the Senate district containing House 28 {q}',
            'SNAP participation gap in House 28 for the whole county', 'For the whole county, what is the SNAP participation gap in House 28?',
            f'How many residents of House 28 on Oahu {q}', f'How many Big Island residents in House 28 {q}',
            f'How many residents in House 28 by ZIP code {q}', f'How many residents in each census tract of House 28 {q}',
            f'How many residents in the old House 28 {q}', f'How many residents in former House 28 {q}',
            f'Using the 2022 lines, how many House 28 residents {q}', f'Not on the 2022 map: how many House 28 residents {q}',
            f'How many residents in Hilo, House 28, {q}', f'How many residents of House 28 in Hilo {q}',
            f'How many residents in Kailua, House 28 {q}',   # an unlisted place is caught by position, not by name
            f'How many residents in part of House 28 {q}', f'How many residents across House 28 and its neighbors {q}',
            f'How many House 28 or 29 residents {q}']
        for text in texts:
            with self.subTest(text=text):
                p = self.prepared(text)
                self.assertIsNone(snap_gap_offer(p))
                out = convert_decision(p, decision('propose', 'create_plan', wire), self.i.core)
                self.assertEqual((out['status'], out['normalized_plan']), ('unsupported', None))
                self.assertNotIn('participation_gap', out)
                own = convert_decision(p, decision('unsupported', reason='unavailable_evidence'), self.i.core)
                self.assertEqual(own['reason_code'], 'unavailable_evidence')
                self.assertNotIn('participation_gap', own)

    def test_coordinated_program_gaps_refuse_a_substitute_plan_without_the_snap_offer(self):
        # Browser reproduction: a valid replace_plan with median household income must not run as the Answer.
        income = wire_plan(dict(food_assistance_recipe(H28), steps=[{'step_id': 's1', 'operation': 'profile', 'args': {'metric_ids': ['median_household_income']}}]))
        income['map_session'] = 0
        for text in ('What are the SNAP and WIC enrollment gaps in House 28?', 'Show the SNAP, WIC and Med-QUEST participation gaps for House 28.',
                     'What is the take-up gap for SNAP or Medicaid in House 28?', 'SNAP/WIC enrollment gap in House 28'):
            for intent in ('create_plan', 'replace_plan'):
                with self.subTest(text=text, intent=intent):
                    p = self.prepared(text)
                    self.assertTrue(coordinated_gap_asked(p))
                    self.assertIsNone(snap_gap_offer(p))
                    out = convert_decision(p, decision('propose', intent, income), self.i.core)
                    self.assertEqual((out['status'], out['intent'], out['reason_code'], out['normalized_plan'], out['recovered_from']),
                                     ('unsupported', 'none', 'unsupported_operation', None, 'unsupported_explicit_constraint'))
                    self.assertNotIn('participation_gap', out)
            own = convert_decision(self.prepared(text), decision('unsupported', reason='unavailable_evidence'), self.i.core)
            self.assertEqual(own['reason_code'], 'unavailable_evidence'); self.assertNotIn('participation_gap', own)
        unc = convert_decision(self.prepared('What are the SNAP and WIC enrollment gaps in House 28?'), decision('uncertain', reason='uncertain_interpretation'), self.i.core)
        self.assertEqual(unc['status'], 'uncertain')

    def test_ordinary_multi_program_requests_still_propose(self):
        evidence = wire_plan(dict(food_assistance_recipe(H28), issue_id='custom', steps=[{'step_id': 's1', 'operation': 'program_evidence', 'args': {'program_ids': ['snap_hi', 'wic_hi']}}]))
        evidence['map_session'] = 0
        income = wire_plan(dict(food_assistance_recipe(H28), steps=[{'step_id': 's1', 'operation': 'profile', 'args': {'metric_ids': ['median_household_income']}}]))
        income['map_session'] = 0
        for text, wire in (('Show SNAP and WIC program info for House 28.', evidence),
                           ('Show median household income for House 28; WIC and SNAP are both relevant.', income),
                           ('Not the SNAP and WIC enrollment gaps; show median household income in House 28.', income)):
            with self.subTest(text=text):
                p = self.prepared(text)
                self.assertFalse(coordinated_gap_asked(p))
                out = convert_decision(p, decision('propose', 'create_plan', wire), self.i.core)
                self.assertEqual(out['status'], 'propose')
                self.assertNotIn('participation_gap', out)

    def test_snap_eligible_but_unenrolled_wording(self):
        self.assertEqual(snap_gap_offer(self.prepared('How many SNAP-eligible but unenrolled people live in House 28?')), OFFER_28)
        for text in ('How many SNAP-eligible but unenrolled people live near House 28?',
                     'How many SNAP-eligible but unenrolled in Medicaid people live in House 28?',
                     'How many WIC-eligible but unenrolled people live in House 28?',
                     'How many people eligible for Medicare but unenrolled live in House 28?'):
            with self.subTest(text=text):
                p = self.prepared(text)
                self.assertIsNone(snap_gap_offer(p))
                self.assertNotIn('participation_gap', convert_decision(p, decision('unsupported', reason='unsupported_operation'), self.i.core))

    def test_clause_level_coordinated_gap_paraphrases_refuse_without_offer(self):
        income = wire_plan(dict(food_assistance_recipe(H28), steps=[{'step_id': 's1', 'operation': 'profile', 'args': {'metric_ids': ['median_household_income']}}]))
        income['map_session'] = 0
        for text in ('What are the SNAP and WIC enrollment gaps in House 28?', 'What are the enrollment gaps for both SNAP and WIC in House 28?',
                     'How large are the SNAP enrollment gap and the WIC enrollment gap in House 28?',
                     'Show the SNAP enrollment gap for House 28 but not WIC.'):   # SNAP gap beside a negated program: refused, no offer
            with self.subTest(text=text):
                p = self.prepared(text)
                out = convert_decision(p, decision('propose', 'replace_plan', income), self.i.core)
                self.assertEqual((out['status'], out['normalized_plan'], out['reason_code']), ('unsupported', None, 'unsupported_operation'))
                self.assertNotIn('participation_gap', out)
                self.assertEqual(convert_decision(p, decision('uncertain', reason='uncertain_interpretation'), self.i.core)['status'], 'uncertain')
        evidence = wire_plan(dict(food_assistance_recipe(H28), issue_id='custom', steps=[{'step_id': 's1', 'operation': 'program_evidence', 'args': {'program_ids': ['snap_hi', 'wic_hi']}}]))
        evidence['map_session'] = 0
        for text, wire in (('Show SNAP and WIC program information for House 28; the enrollment gap is a separate memo.', evidence),
                           ('Not the SNAP and WIC enrollment gaps; show median household income in House 28.', income)):
            with self.subTest(text=text):
                self.assertEqual(convert_decision(self.prepared(text), decision('propose', 'create_plan', wire), self.i.core)['status'], 'propose')

    def test_unknown_place_scoping_the_district_population_withholds_the_offer(self):
        q = 'qualify for SNAP but aren\u2019t enrolled?'
        for text in (f'How many House 28 residents in Kailua {q}', f'How many Kailua residents of House 28 {q}',
                     f'How many residents of House 28 living in Kailua {q}', f'How many residents of Kailua in House 28 {q}',
                     f'In Kailua, how many House 28 residents {q}', f'How many House 28 residents at Kailua Beach {q}'):
            with self.subTest(text=text):
                p = self.prepared(text)
                self.assertIsNone(snap_gap_offer(p))
                out = convert_decision(p, decision('unsupported', reason='unsupported_operation'), self.i.core)
                self.assertEqual(out['reason_code'], 'unsupported_operation'); self.assertNotIn('participation_gap', out)
        # No false veto for "in SNAP" or a direct "in House 28".
        for text in ('How many residents in House 28 qualify for SNAP but aren\u2019t enrolled in SNAP?',
                     'Eligible non-participants for food stamps in house district 28?', COLD):
            with self.subTest(text=text):
                self.assertEqual(snap_gap_offer(self.prepared(text)), OFFER_28)

    def test_offer_only_for_supported_vocabulary_unknown_program_or_subarea_withheld(self):
        income = wire_plan(dict(food_assistance_recipe(H28), steps=[{'step_id': 's1', 'operation': 'profile', 'args': {'metric_ids': ['median_household_income']}}]))
        income['map_session'] = 0
        withheld = ['What is the SNAP enrollment gap for the northern half of House 28?',      # reviewer reproductions
                    'What is the participation gap for SNAP and TANF in House 28?']
        withheld += [f'What is the participation gap for SNAP and {prog} in House 28?' for prog in ('TANF', 'LIHEAP', 'Medicare', 'SSI', 'Zorblax')]
        withheld += [f'What is the SNAP enrollment gap for the {area} of House 28?' for area in
                     ('northern half', 'south side', 'east end', 'upper valley', 'mauka part', 'Zorblax quarter')]
        withheld += ['How many low-income residents of House 28 qualify for SNAP but aren\u2019t enrolled?',
                     'How many House 28 residents qualify for SNAP but aren\u2019t enrolled this year?']
        for text in withheld:
            with self.subTest(text=text):
                p = self.prepared(text)
                self.assertIsNone(snap_gap_offer(p))
                own = convert_decision(p, decision('unsupported', reason='unavailable_evidence'), self.i.core)
                self.assertEqual((own['status'], own['reason_code']), ('unsupported', 'unavailable_evidence'))
                self.assertNotIn('participation_gap', own)
                sub = convert_decision(p, decision('propose', 'replace_plan', income), self.i.core)
                self.assertEqual((sub['status'], sub['normalized_plan']), ('unsupported', None))   # never a substitute plan
                self.assertNotIn('participation_gap', sub)
        for text in (COLD, 'What is the SNAP enrollment gap in House 28?', 'What is the participation gap in SNAP for House 28?',
                     'Show the SNAP participation gap in House 28.', 'Give me a brief on the SNAP take-up gap for House 28.',
                     'How many House 28 residents qualify for SNAP but aren\u2019t enrolled? I need it for a meeting.',
                     'How many people in House 28 are eligible for SNAP but not signed up?'):
            with self.subTest(text=text):
                self.assertEqual(snap_gap_offer(self.prepared(text)), OFFER_28)

    def test_request_clause_observation_table(self):
        def w(issue, steps):
            x = wire_plan(dict(food_assistance_recipe(H28), issue_id=issue, steps=steps)); x['map_session'] = 0; return x
        income = w('custom', [{'step_id': 's1', 'operation': 'profile', 'args': {'metric_ids': ['median_household_income']}}])
        snap_info = w('custom', [{'step_id': 's1', 'operation': 'program_evidence', 'args': {'program_ids': ['snap_hi']}}])
        population = w('custom', [{'step_id': 's1', 'operation': 'profile', 'args': {'metric_ids': ['total_population']}}])
        # (question, valid proposal, expected status, offer?)
        table = (
            ('I am studying the SNAP enrollment gap. What is median household income in House 28?', income, 'propose', False),
            ('I am studying the SNAP enrollment gap. Show me SNAP program information for House 28.', snap_info, 'propose', False),
            ('What is the gap in SNAP take-up for House 28?', income, 'unsupported', True),
            ('How many House 28 households are entitled to SNAP but not receiving it?', income, 'unsupported', True),
            ('I want the SNAP enrollment gap for House 28.', income, 'unsupported', False),   # a first-person request still refuses
            ('We are studying SNAP and WIC enrollment gaps. Show SNAP and WIC program info for House 28.',
             w('custom', [{'step_id': 's1', 'operation': 'program_evidence', 'args': {'program_ids': ['snap_hi', 'wic_hi']}}]), 'propose', False),
            ('I am studying WIC. What is the SNAP enrollment gap in House 28?', income, 'unsupported', False),
            (COLD, income, 'unsupported', True),
            ('The SNAP enrollment gap matters to us. What is median household income in House 28?', income, 'propose', False),
            ('SNAP enrollment is a staff priority; show SNAP program info in House 28', snap_info, 'propose', False),
            ('SNAP enrollment gap in House 28', income, 'unsupported', True),                  # one-sentence shorthand
            # A gap in a purpose or context phrase is not what is asked: the income request runs.
            ('For our SNAP enrollment gap meeting, what is median household income in House 28?', income, 'propose', False),
            ('Show median household income in House 28 for a presentation on the SNAP enrollment gap.', income, 'propose', False),
            ('We are studying the SNAP enrollment gap, but today I only need median household income in House 28.', income, 'propose', False),
            ('Show SNAP program information for House 28 so our team can estimate the SNAP enrollment gap.', snap_info, 'propose', False),
            ('Show median household income for House 28 as background for a brief on the SNAP enrollment gap.', income, 'propose', False),
            ('Show median household income in House 28 for a meeting about families entitled to SNAP but not receiving it.', income, 'propose', False),
            # A counted population with its own predicate ("live in House 28") is not the eligibility form in a purpose phrase.
            ('How many people live in House 28, as background for outreach to families entitled to SNAP but not receiving it?', population, 'propose', False),
            ('How many people live in House 28 for our meeting about families entitled to SNAP but not receiving it?', population, 'propose', False),
            ('What is the number of House 28 residents for a meeting about families entitled to SNAP but not receiving it?', population, 'propose', False),
            ('How many people in House 28 regardless of whether they are entitled to SNAP but not receiving it?', population, 'propose', False),
            ('How many residents of House 28 are entitled to SNAP but not receiving it?', population, 'unsupported', True),
            ('How many people in House 28 are entitled to SNAP but not receiving it?', population, 'unsupported', True),
            ('How many House 28 households are entitled to SNAP but not receiving it?', population, 'unsupported', True),
            # A bare gap is the whole clause only; a declaration with its own verb and a separate request is context.
            ('The SNAP enrollment gap in House 28 is on our agenda, so what is the median household income there?', income, 'propose', False),
            ('The SNAP enrollment gap in House 28 is our concern, but today we only need total population.', population, 'propose', False),
            ('The SNAP enrollment gap in House 28', income, 'unsupported', True),
            ('Show the SNAP enrollment gap in House 28.', income, 'unsupported', True),
            ('What is the SNAP enrollment gap in House 28?', income, 'unsupported', True),
            ('Give me a brief on the SNAP take-up gap for House 28.', income, 'unsupported', True),
        )
        for text, wire, status, offered in table:
            with self.subTest(text=text):
                p = self.prepared(text)
                out = convert_decision(p, decision('propose', 'replace_plan', wire), self.i.core)
                self.assertEqual(out['status'], status)
                if status == 'unsupported':
                    self.assertEqual((out['normalized_plan'], out['reason_code']), (None, 'unsupported_operation'))
                self.assertEqual(out.get('participation_gap'), OFFER_28 if offered else None)
                own = convert_decision(p, decision('unsupported', reason='unavailable_evidence'), self.i.core)
                self.assertEqual((own['reason_code'], own.get('participation_gap')), ('unavailable_evidence', OFFER_28 if offered else None))

    def test_named_district_is_used_never_the_held_one(self):
        p = self.prepared(COLD.replace('28', '5'), held=recipe(dict(H28, code='013')))
        self.assertEqual(snap_gap_offer(p)['district'], dict(H28, code='005'))

    def test_offer_only_on_unsupported_and_only_with_the_recipe_admitted(self):
        p = self.prepared(COLD)
        for d in (decision('uncertain', reason='uncertain_interpretation'),):
            self.assertNotIn('participation_gap', convert_decision(p, d, self.i.core))
        p['provider_context']['catalog']['recipes'] = [r for r in p['provider_context']['catalog']['recipes'] if r != 'food_assistance_outreach/1']
        self.assertIsNone(snap_gap_offer(p))
        self.assertNotIn('participation_gap', convert_decision(p, decision('unsupported', reason='unavailable_evidence'), self.i.core))


class JobTests(Base):
    """The exact cold input through the asynchronous job with a production-shaped offline provider stub."""

    def run_job(self, wire_decision):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        calls = []

        def transport(method, path, body, secret, deadline):
            calls.append(path)
            if path.endswith('input_tokens'):
                return 200, {'object': 'response.input_tokens', 'input_tokens': 1000}
            return 200, {'model': 'gpt-6.1-terra', 'service_tier': 'default', 'reasoning': {'effort': 'medium'}, 'status': 'completed', 'usage': usage(),
                         'output': [{'type': 'function_call', 'name': 'ia_language_decision', 'status': 'completed', 'arguments': json.dumps(wire_decision)}]}
        service = LanguageService(self.i, enabled=True, provider=OpenAIProvider(transport=transport, secret_reader=lambda: 'fake-no-network'), ledger=ledger_fixture(tmp.name))
        self.addCleanup(service.close)
        r = self.request(COLD)
        self.assertEqual(service.handle('start', r, 'a')[0], 202)
        self.assertTrue(service._jobs[r['request_id']]['done'].wait(5))
        code, out = service.handle('status', {'schema_version': SCHEMA_VERSION, 'request_id': r['request_id']}, 'a')
        self.assertEqual(code, 200)
        return out, calls

    def test_cold_input_job_returns_offer_with_one_model_call_and_no_count(self):
        out, calls = self.run_job(decision('unsupported', reason='unavailable_evidence'))
        self.assertEqual((out['status'], out['model_calls'], out['participation_gap']), ('unsupported', 1, OFFER_28))
        self.assertEqual(sum(1 for c in calls if not c.endswith('input_tokens')), 1, 'only the original question reaches the provider')
        self.assert_value_free(out)
        self.assertFalse(re.search(r'\d', out['message']))

    def test_interpretation_failure_carries_no_offer(self):
        bad = decision('unsupported', reason='missing_context')  # invalid unsupported reason: refused as uncertain
        out, _ = self.run_job(bad)
        self.assertEqual(out['status'], 'uncertain')
        self.assertNotIn('participation_gap', out)


class CleanCheckoutTests(unittest.TestCase):
    """No site provider: Ask is off, no offer or model call exists, and Typed request still refuses the cold input."""

    def test_no_provider_keeps_language_off_and_typed_request_unchanged(self):
        with tempfile.TemporaryDirectory() as state:
            app = Application(state, secure_cookie=False)
            self.addCleanup(app.language.close)
            for h in app.service.metrics.handlers:
                self.addCleanup(h.close)
            self.assertFalse(app.language.bootstrap()['enabled'])
            code, out = app.language.handle('start', {'schema_version': SCHEMA_VERSION, 'utterance': COLD}, 'a')
            self.assertEqual((code, out['model_calls']), (503, 0))
            self.assertNotIn('participation_gap', out)
            i = app.investigation
            held = recipe(H28)
            r = {'schema_version': 'haic-investigation/1', 'request_id': str(uuid.uuid4()), 'case_id': str(uuid.uuid4()), 'branch_id': str(uuid.uuid4()),
                 'revision': 1, 'operation_version': 'ia-core/1', 'recipe_version': 'aging_at_home/1', 'snapshot_id': i.snapshot_id,
                 'mode': 'interpret', 'plan': held, 'utterance': COLD}
            typed = i.handle(r)
            self.assertEqual((typed['status'], typed['normalized_plan'], typed['model_calls']), ('unsupported', held, 0))
            self.assertNotIn('participation_gap', typed)


class OutreachBriefTests(Base):
    """What the offer opens: the existing checked SNAP outreach recipe, its action and a brief without any count."""

    def test_offered_recipe_runs_and_briefs_with_the_staff_data_check(self):
        plan = food_assistance_recipe(H28)
        ids = {k: str(uuid.uuid4()) for k in ('request_id', 'case_id', 'branch_id')}
        run = {**ids, 'schema_version': 'haic-investigation/1', 'revision': 2, 'operation_version': 'ia-core/1', 'recipe_version': 'food_assistance_outreach/1',
               'snapshot_id': self.i.snapshot_id, 'mode': 'run', 'plan': plan, 'selected_claim_refs': [], 'selected_action_ref': None}
        out = self.i.handle(run)
        self.assertEqual((out['status'], out['model_calls']), ('ok', 0))
        snap = next(c for c in out['responses'] if c['program_id'] == 'snap_hi')
        self.assertEqual(snap['action_ref']['action_id'], 'snap_food_outreach_verify/1')
        self.assertTrue(any('BESSD' in q for q in snap['facts_to_verify']))
        refs = [c['claim_ref'] for c in out['claims'] if c['kind'] in ('outreach_hypothesis', 'program_relevance')]
        self.assertLessEqual(len(GAP_CHECK), 120)
        brief = dict(run, request_id=str(uuid.uuid4()), mode='brief', selected_claim_refs=refs, selected_action_ref=snap['action_ref'],
                     staff_edits={}, checklist_edits=[{'item_id': 'custom1', 'text': GAP_CHECK}], tracking=None, edits_reviewed_for=None)
        with self.assertRaises(Exception) as unreviewed:
            self.i.handle(brief)
        self.assertEqual(getattr(unreviewed.exception, 'code', None), 'staff_review_required')
        brief['edits_reviewed_for'] = {'branch_id': run['branch_id'], 'revision': 2, 'plan_hash': plan_hash(plan)}
        html = self.i.handle(brief)['brief']['html']
        self.assertIn('BESSD', html)
        self.assertIn(GAP_CHECK, html)
        for figure in self.figures:
            self.assertNotIn(figure, html)


if __name__ == '__main__':
    unittest.main()

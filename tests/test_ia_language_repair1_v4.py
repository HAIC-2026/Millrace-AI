"""Repair-1 v4 regressions for the independent source-v3 review findings (F1-F8). Injected decisions only: no network,
model, Count or credential. Contexts are the real UI shapes (the boot default House 028 aging plan held as both
confirmed and draft, an edited draft, an explicit step focus, an inspected current finding) and, separately, the API
empty context that the old benchmark uses."""
import copy
import json
import unittest
import uuid
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.interpret import food_assistance_recipe, recipe
from districtbrief.ia_language import SCHEMA_VERSION, LanguageError, convert_decision, prepare_request, wire_plan
from districtbrief.ia_language_provider import PROMPT

def D(chamber, code): return {'state_fips': '15', 'chamber': chamber, 'code': code, 'boundary_session': 2024}
def plan(district, steps, issue='custom', map_session=2026):
    return {'district': district, 'map_session': map_session, 'issue_id': issue, 'service_area_id': None, 'steps': steps}
def prof(*m, sid='s1'): return {'step_id': sid, 'operation': 'profile', 'args': {'metric_ids': list(m)}}
def cmp(g, *m, sid='s2'): return {'step_id': sid, 'operation': 'compare', 'args': {'metric_ids': list(m), 'comparison_geography': g}}
UI_DEFAULT = recipe(D('house', '028'))           # static/case_state.js defaultPlan(): House 028, aging, map 2026
H12 = plan(D('house', '012'), [prof('median_age')])
SENTINEL = {'district': {'chamber': '', 'code': ''}, 'map_session': 0, 'issue_id': '', 'service_area_id': '', 'steps': []}

class Repair1V4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.i = Investigation(load_core())
    def request(self, text, confirmed=None, draft='same', focus=None, refs=()):
        draft = copy.deepcopy(confirmed) if draft == 'same' else draft
        held = confirmed or draft
        return {'schema_version': SCHEMA_VERSION, 'request_id': str(uuid.uuid4()), 'utterance': text, 'context': {
            'case_id': str(uuid.uuid4()), 'branch_id': str(uuid.uuid4()), 'revision': 1, 'snapshot_id': self.i.snapshot_id,
            'operation_version': 'ia-core/1', 'recipe_version': (held['issue_id'] if held else 'custom') + '/1',
            'confirmed_plan': copy.deepcopy(confirmed), 'draft_plan': copy.deepcopy(draft), 'focused_step_id': focus,
            'selected_claim_refs': list(refs)}}
    def prepared(self, *a, **kw): return prepare_request(self.request(*a, **kw), self.i, 's')
    def propose(self, p, wire_map=0, intent='replace_plan'):
        return {'status': 'propose', 'intent': intent, 'plan': dict(wire_plan(p), map_session=wire_map), 'focus_alias': '',
                'clarify_field': '', 'clarify_choices': [], 'reason_code': '', 'inherited_fields': []}
    def clarify(self, field, choices):
        return {'status': 'clarify', 'intent': 'none', 'plan': SENTINEL, 'focus_alias': '', 'clarify_field': field,
                'clarify_choices': list(choices), 'reason_code': 'missing_context', 'inherited_fields': []}
    def run_(self, text, decision, *a, **kw): return convert_decision(self.prepared(text, *a, **kw), decision, self.i.core)
    def refused(self, text, decision, *a, **kw):
        with self.assertRaises(LanguageError) as c: self.run_(text, decision, *a, **kw)
        return c.exception.code

    # ---- F1/F5: map year, negation and false positives (held confirmed House 12, and the UI default House 028)
    def test_f1_negated_map_phrases_keep_the_held_map_and_never_accept_the_excluded_year(self):
        for held, p in ((H12, H12), (UI_DEFAULT, UI_DEFAULT)):
            for text in ("Profile median age for House 12; don't switch the map to 2024.", "Don't show the 2024 boundary on the map.",
                         'Never put the 2024 boundary on the map.', 'Keep this plan without switching the map to 2024.',
                         'Do not change the map to 2024.', "Keep this plan but don't switch the map to 2024.", "Don't switch to the 2024 map."):
                if held is UI_DEFAULT: text = text.replace('Profile median age for House 12', 'Keep this House 28 plan')
                with self.subTest(held=held['district']['code'], text=text):
                    self.assertEqual(self.run_(text, self.propose(p, 0), held)['normalized_plan']['map_session'], 2026)
                    self.assertIn(self.refused(text, self.propose(p, 2024), held), ('explicit_map_conflict', 'explicit_map_unstated_change'))

    def test_f1_positive_wordings_still_select_the_year_and_unproven_negation_fails_closed(self):
        for text in ('Switch the map to 2024.', 'Show the 2024 boundary on the map.', 'Put this on the 2024 map.', 'Change the map to the 2024 session.'):
            with self.subTest(text=text):
                self.assertEqual(self.run_(text, self.propose(UI_DEFAULT, 2024), UI_DEFAULT)['normalized_plan']['map_session'], 2024)
                self.assertEqual(self.refused(text, self.propose(UI_DEFAULT, 0), UI_DEFAULT), 'explicit_map_unreported')
        # "Don't change the (current) map" keeps; "don't change the 2024 map" keeps 2024 (never an exclusion).
        self.assertEqual(self.run_("Keep this plan; don't change the current map.", self.propose(UI_DEFAULT, 0), UI_DEFAULT)['normalized_plan']['map_session'], 2026)
        h24 = dict(H12, map_session=2024)
        self.assertEqual(self.run_("Profile median age for House 12; don't change the 2024 map.", self.propose(h24, 2024), h24)['normalized_plan']['map_session'], 2024)
        # A negation the grammar cannot attribute: refuse both years rather than guess.
        for text in ("I don't want you to switch the map to 2024.", "Don't switch the map from 2026 to 2024."):
            for m in (0, 2024):
                with self.subTest(text=text, m=m):self.assertEqual(self.refused(text, self.propose(H12, m), H12), 'explicit_map_ambiguous')

    def test_f5_estimates_and_legend_are_not_map_years(self):
        for text in ('Profile House 12 median age and map to 2024 estimates.', 'Profile House 12 median age from the 2024 boundaries in the map legend.',
                     'Profile House 12 median age using the 2024 boundaries.'):
            with self.subTest(text=text):
                self.assertEqual(self.run_(text, self.propose(H12, 0), H12)['normalized_plan']['map_session'], 2026)
                self.assertEqual(self.refused(text, self.propose(H12, 2024), H12), 'explicit_map_unstated_change')

    # ---- E06/X20 negated imperatives never accept the wrong scope
    def test_negated_district_move_and_step_retarget_fail_closed(self):
        s21 = plan(D('senate', '021'), [prof('median_age')]); s22 = dict(s21, district=D('senate', '022'))
        for p in (s21, s22):
            self.assertEqual(self.refused("Don't move this plan from Senate 21 to Senate 22.", self.propose(p), s21), 'explicit_district_ambiguous')
        self.assertEqual(self.run_('Move this plan from Senate 21 to Senate 22.', self.propose(s22), s21)['normalized_plan']['district'], D('senate', '022'))
        retarget = copy.deepcopy(UI_DEFAULT); retarget['steps'][1]['args']['comparison_geography'] = 'HI-SENATE-023-2024'
        for p in (UI_DEFAULT, retarget):
            self.assertEqual(self.refused("Don't point this step at Senate 23.", self.propose(p), UI_DEFAULT, focus='s2'), 'explicit_district_ambiguous')

    # ---- F2/F3: a named recipe is a default; negation, replacement, omit/add edits are all valid proposals
    def test_f2_f3_recipe_negation_replacement_and_edits_are_accepted(self):
        s23 = plan(D('senate', '023'), [prof('median_age')]); h28 = plan(D('house', '028'), [prof('median_age')])
        food = food_assistance_recipe(D('house', '028'))
        for text, p, held in (('Instead of SNAP outreach, profile median age for Senate 23.', s23, None),
                              ('Rather than aging at home, profile median age for Senate 23.', s23, None),
                              ('Switch from SNAP outreach to a median age profile for House 28.', h28, food),
                              ('Replace the SNAP outreach plan with just a median age profile.', h28, food),
                              ('Stop the SNAP outreach and profile median age instead.', h28, food)):
            with self.subTest(text=text):
                self.assertEqual(self.run_(text, self.propose(p, intent='replace_plan' if held else 'create_plan'), held)['normalized_plan']['issue_id'], 'custom')
        f23 = food_assistance_recipe(D('senate', '023'))
        no_lead = copy.deepcopy(f23); no_lead['steps'].pop()
        plus_age = copy.deepcopy(f23); plus_age['steps'][0]['args']['metric_ids'].append('median_age')
        plus_wic = copy.deepcopy(f23); plus_wic['steps'][1]['args']['program_ids'].append('wic_hi')
        a25 = recipe(D('senate', '025')); a25_no_lead = copy.deepcopy(a25); a25_no_lead['steps'].pop()
        for text, p, held in (('Run SNAP outreach for Senate 23 without the outreach lead.', no_lead, None),
                              ('Run SNAP outreach for Senate 23 and include median age in its profile.', plus_age, None),
                              ('Run SNAP outreach for Senate 23 and also add WIC to its program references.', plus_wic, None),
                              ('Set up older-adult support at home for Senate 25 but skip the outreach lead.', a25_no_lead, None),
                              ('Set up older-adult support at home for Senate 25 but skip the outreach lead.', a25_no_lead, UI_DEFAULT)):
            with self.subTest(text=text, ui=held is not None):
                self.assertEqual(self.run_(text, self.propose(p, intent='replace_plan' if held else 'create_plan'), held)['status'], 'propose')

    def test_implicit_recipe_metric_grounding_respects_negated_and_replaced_mentions(self):
        aging_cmp = dict(plan(D('house', '012'), [prof('median_age'), cmp('HI-STATE-2024', 'poverty_rate_65_plus')]), issue_id='aging_at_home')
        out = self.run_('Run aging at home for House 12 and compare poverty with the State.', self.propose(aging_cmp), H12)
        self.assertEqual(out['status'], 'propose')  # positive recipe mention: its canonical poverty metric is the default
        out = self.run_('Instead of aging at home, compare poverty with House 12 against the State.', self.propose(aging_cmp), H12)
        self.assertEqual((out['status'], out['clarify_field']), ('clarify', 'metric'))  # negated mention grounds nothing

    # ---- F4: real UI shape (default House 028 held as confirmed and draft, focused_step_id null unless chosen)
    def test_f4_unfocused_comparison_retarget_in_the_ui_default_uses_its_only_compare_step(self):
        retarget = copy.deepcopy(UI_DEFAULT); retarget['steps'][1]['args']['comparison_geography'] = 'HI-SENATE-023-2024'
        moved = dict(copy.deepcopy(UI_DEFAULT), district=D('senate', '023'))
        for focus in (None, 's2'):
            with self.subTest(focus=focus):
                out = self.run_('Point this comparison at Senate 23.', self.propose(retarget), UI_DEFAULT, focus=focus)
                self.assertEqual((out['normalized_plan']['district'], [x['step_id'] for x in out['typed_diff']]), (D('house', '028'), ['s2']))
                self.assertEqual(self.refused('Point this comparison at Senate 23.', self.propose(moved), UI_DEFAULT, focus=focus), 'explicit_district_conflict')
        self.assertEqual(self.refused('Point this step at Senate 23.', self.propose(retarget), UI_DEFAULT, focus='s1'), 'explicit_step_focus_missing')
        # A changed other step is not a retarget.
        other = copy.deepcopy(retarget); other['steps'][0]['args']['metric_ids'] = ['median_age']
        self.assertEqual(self.refused('Point this comparison at Senate 23.', self.propose(other), UI_DEFAULT), 'explicit_comparator_conflict')
        # The focus must be a step of the held plan (server validation of the client focus).
        with self.assertRaises(LanguageError) as c: self.prepared('Point this step at Senate 23.', UI_DEFAULT, focus='s9')
        self.assertEqual(c.exception.code, 'invalid_focus')

    def test_f4a_f8_ungrounded_place_or_identity_district_lists_are_replaced_in_ui_and_api_contexts(self):
        hilo = ['d_h002', 'd_h003', 'd_h004', 'd_s001', 'd_s002']
        for held in (UI_DEFAULT, None):
            for text, choices in (('Senior poverty around Hilo.', hilo), ('Poverty for kids under 5 in my district.', ['d_h001', 'd_h002']),
                                  ('Unemployment rate for the district I represent, age 25 to 34.', ['d_h025', 'd_s025'])):
                with self.subTest(text=text, ui=held is not None):
                    out = self.run_(text, self.clarify('district', choices), held)
                    self.assertEqual((out['clarify_field'], [c['alias'] for c in out['choices']], out['recovered_from']),
                                     ('chamber', ['c_house', 'c_senate'], 'explicit_district_missing'))
        # Grounded choices stand: the held (visible) district, or districts the question names.
        self.assertIsNone(self.run_('How does it look here?', self.clarify('district', ['d_h028']), UI_DEFAULT).get('recovered_from'))
        self.assertIsNone(self.run_("Show median age for our Senate seat - it's district 1 or 2.", self.clarify('district', ['d_s001', 'd_s002']), UI_DEFAULT).get('recovered_from'))
        self.assertIsNone(self.run_('Show median age for our Senate seat 1 or 2.', self.clarify('district', ['d_s001', 'd_s002'])).get('recovered_from'))
        out = self.run_('Profile median age in a senate district near Hilo.', self.clarify('district', ['d_s001', 'd_s002']), UI_DEFAULT)
        self.assertEqual((out['clarify_field'], len(out['choices'])), ('district', 25))  # stated chamber: complete list

    def test_own_district_wording_is_never_answered_by_the_visible_default_district(self):
        u = 'I want the unemployment rate for the district I represent.'
        h28 = plan(D('house', '028'), [prof('unemployment_rate')])
        for decision in (self.propose(h28), self.clarify('district', ['d_h028'])):
            out = self.run_(u, decision, UI_DEFAULT)
            self.assertEqual((out['clarify_field'], [c['alias'] for c in out['choices']], out['recovered_from']),
                             ('chamber', ['c_house', 'c_senate'], 'explicit_district_missing'))
        self.assertEqual(len(self.run_('Unemployment rate for my House district.', self.propose(h28), UI_DEFAULT)['choices']), 51)
        # "Here"/"this plan" still uses the visible held district, and the chosen canonical prefix resolves identity wording.
        self.assertEqual(self.run_('What is the unemployment rate here?', self.propose(h28), UI_DEFAULT)['status'], 'propose')
        h5 = plan(D('house', '005'), [prof('unemployment_rate')])
        self.assertEqual(self.run_('House 5: ' + u, self.propose(h5), UI_DEFAULT)['normalized_plan']['district'], D('house', '005'))

    # ---- F6: the next request after a choice names the chosen district; the confirmed/draft basis is honoured
    def test_f6_next_request_after_district_choice_and_conflict_basis(self):
        h5 = dict(copy.deepcopy(UI_DEFAULT), district=D('house', '005'))
        out = self.run_('Switch to district 5 and show senior poverty.', self.propose(h5), UI_DEFAULT)
        self.assertEqual(out['clarify_field'], 'district')  # ambiguous bare number: d_h005/d_s005
        out = self.run_('House 5: Switch to district 5 and show senior poverty.', self.propose(h5), UI_DEFAULT)  # client prefix
        self.assertEqual((out['status'], out['normalized_plan']['district']), ('propose', D('house', '005')))
        draft = copy.deepcopy(UI_DEFAULT); draft['steps'].pop()
        both = dict(copy.deepcopy(draft)); both['steps'].append(prof('median_age', sid='s5'))
        out = self.run_('Also add median age.', self.propose(both), UI_DEFAULT, draft)
        self.assertEqual(out['clarify_field'], 'control_conflict')
        out = self.run_('Also add median age.', self.propose(both), None, draft)  # basis 'draft': no confirmed plan sent
        self.assertEqual((out['status'], out['inherited_fields']), ('propose', []))
        conf = copy.deepcopy(UI_DEFAULT); conf['steps'].append(prof('median_age', sid='s5'))
        out = self.run_('Also add median age.', self.propose(conf), UI_DEFAULT, copy.deepcopy(UI_DEFAULT))  # basis 'confirmed'
        self.assertEqual(out['status'], 'propose')

    # ---- F7: an inspected current finding is the question's single referent; a stale one is refused
    def test_f7_inspected_finding_is_the_source_question_referent(self):
        run = self.i.handle({'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1', 'recipe_version': 'aging_at_home/1',
            'snapshot_id': self.i.snapshot_id, 'request_id': str(uuid.uuid4()), 'case_id': str(uuid.uuid4()), 'branch_id': str(uuid.uuid4()),
            'revision': 1, 'mode': 'run', 'plan': copy.deepcopy(UI_DEFAULT), 'selected_claim_refs': [], 'selected_action_ref': None})
        ref = next(c['claim_ref'] for c in run['claims'] if c['kind'] == 'comparison')
        u = 'Explain the source I just selected for senior poverty in House 028.'
        p = self.prepared(u, UI_DEFAULT, refs=[ref])
        self.assertEqual(list(p['provider_context']['selected']), ['selected_1'])
        self.assertNotIn('value', json.dumps(p['provider_context']['selected']).lower().replace('values', ''))
        d = {'status': 'propose', 'intent': 'inspect_source', 'plan': copy.deepcopy(SENTINEL), 'focus_alias': 'selected_1', 'clarify_field': '',
             'clarify_choices': [], 'reason_code': '', 'inherited_fields': []}
        out = convert_decision(p, d, self.i.core)
        self.assertEqual((out['intent'], bool(out['source_inspection_refs'])), ('inspect_source', True))
        stale = dict(ref, semantic_hash='sha256:' + '0' * 64)
        with self.assertRaises(LanguageError) as c: self.prepared(u, UI_DEFAULT, refs=[stale])
        self.assertEqual(c.exception.code, 'stale_selection')
        with self.assertRaises(LanguageError): convert_decision(self.prepared(u, UI_DEFAULT), d, self.i.core)  # no referent: never guessed

    def test_prompt_states_the_bounded_rules(self):
        for text in ("a negated map phrase (\"don't switch the map to 2024\") keeps the held map", 'a negated or replaced recipe is not requested',
                     'changes only the comparison geography of focused_step_id', 'district choices are only districts the question names or the held district',
                     'held context never resolves a place name or the asker'):
            self.assertIn(text, PROMPT)

if __name__ == '__main__': unittest.main()

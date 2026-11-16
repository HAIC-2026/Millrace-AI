"""Repair-1 regressions: literal saved model outputs from the (now exposed, development-only) Medium study plus broader
public examples. Injected decisions only: no network, model, Count or credential. Each literal saved output is the
exact function_arguments string the provider returned; the request contexts are the study's own (fresh UUIDs)."""
import copy
import json
import re
import unittest
import uuid
from pathlib import Path
from public_app import load_core
from districtbrief.investigation import Investigation
from districtbrief.interpret import food_assistance_recipe, recipe
from districtbrief.ia_language import (RECIPE_LABELS, SCHEMA_VERSION, LanguageError, convert_decision, prepare_request,
                                       strict_json, wire_plan)
from districtbrief.ia_language_provider import PROMPT
from districtbrief.render import _ISSUE_NAMES
import test_ia_language_map_default as map_tests  # module import: its TestCase is not re-collected here

def D(chamber, code): return {'state_fips': '15', 'chamber': chamber, 'code': code, 'boundary_session': 2024}
def plan(district, steps, issue='custom'):
    return {'district': district, 'map_session': 2026, 'issue_id': issue, 'service_area_id': None, 'steps': steps}
def prof(*m, sid='s1'): return {'step_id': sid, 'operation': 'profile', 'args': {'metric_ids': list(m)}}
def cmp(g, *m, sid='s2'): return {'step_id': sid, 'operation': 'compare', 'args': {'metric_ids': list(m), 'comparison_geography': g}}
STATE = 'HI-STATE-2024'
S21 = plan(D('senate', '021'), [prof('median_age')])
S18 = plan(D('senate', '018'), [prof('unemployment_rate'), cmp(STATE, 'unemployment_rate')])
H25_FOOD = food_assistance_recipe(D('house', '025'))
S12_AGING = recipe(D('senate', '012'))

# Literal saved function_arguments (arm A = gpt-6.1-terra medium, arm B = gpt-6.1-sol low).
SAVED = {
 'E06': '{"clarify_choices":[],"clarify_field":"","focus_alias":"","inherited_fields":["map_session","issue_id","steps"],"intent":"replace_plan","plan":{"district":{"chamber":"senate","code":"022"},"issue_id":"custom","map_session":0,"service_area_id":"","steps":[{"comparison_geography":"","metric_ids":["median_age"],"observation_ids":[],"operation":"profile","program_ids":[],"step_id":"s1"}]},"reason_code":"","status":"propose"}',
 'X20': '{"clarify_choices":[],"clarify_field":"","focus_alias":"","inherited_fields":["district","map_session","issue_id","service_area_id"],"intent":"replace_plan","plan":{"district":{"chamber":"senate","code":"018"},"issue_id":"custom","map_session":0,"service_area_id":"","steps":[{"comparison_geography":"","metric_ids":["unemployment_rate"],"observation_ids":[],"operation":"profile","program_ids":[],"step_id":"s1"},{"comparison_geography":"HI-SENATE-023-2024","metric_ids":["unemployment_rate"],"observation_ids":[],"operation":"compare","program_ids":[],"step_id":"s2"}]},"reason_code":"","status":"propose"}',
 'G05': '{"clarify_choices":[],"clarify_field":"","focus_alias":"","inherited_fields":[],"intent":"create_plan","plan":{"district":{"chamber":"senate","code":"023"},"issue_id":"custom","map_session":0,"service_area_id":"","steps":[{"comparison_geography":"","metric_ids":[],"observation_ids":[],"operation":"outreach_lead","program_ids":["snap_hi"],"step_id":"s1"}]},"reason_code":"","status":"propose"}',
 'G06A': '{"clarify_choices":["p_kupuna_care_hi","p_medquest_hi","p_hcv_honolulu","p_snap_hi","p_wic_hi"],"clarify_field":"program","focus_alias":"","inherited_fields":[],"intent":"none","plan":{"district":{"chamber":"","code":""},"issue_id":"","map_session":0,"service_area_id":"","steps":[]},"reason_code":"missing_context","status":"clarify"}',
 'G06B': '{"clarify_choices":[],"clarify_field":"","focus_alias":"","inherited_fields":[],"intent":"create_plan","plan":{"district":{"chamber":"house","code":"004"},"issue_id":"aging_at_home","map_session":0,"service_area_id":"","steps":[{"comparison_geography":"","metric_ids":["population_65_plus","male_householder_65_plus_living_alone","female_householder_65_plus_living_alone","poverty_rate_65_plus"],"observation_ids":[],"operation":"profile","program_ids":[],"step_id":"s1"},{"comparison_geography":"HI-STATE-2024","metric_ids":["poverty_rate_65_plus"],"observation_ids":[],"operation":"compare","program_ids":[],"step_id":"s2"},{"comparison_geography":"","metric_ids":[],"observation_ids":[],"operation":"program_evidence","program_ids":["kupuna_care_hi"],"step_id":"s3"},{"comparison_geography":"","metric_ids":[],"observation_ids":[],"operation":"outreach_lead","program_ids":["kupuna_care_hi"],"step_id":"s4"}]},"reason_code":"","status":"propose"}',
 'X21': '{"clarify_choices":["d_h025"],"clarify_field":"district","focus_alias":"","inherited_fields":[],"intent":"none","plan":{"district":{"chamber":"","code":""},"issue_id":"","map_session":0,"service_area_id":"","steps":[]},"reason_code":"missing_context","status":"clarify"}',
 'X22': '{"clarify_choices":["d_s012"],"clarify_field":"district","focus_alias":"","inherited_fields":[],"intent":"none","plan":{"district":{"chamber":"","code":""},"issue_id":"","map_session":0,"service_area_id":"","steps":[]},"reason_code":"missing_context","status":"clarify"}',
 'Q01A': '{"clarify_choices":["d_h001","d_h002","d_h003","d_h004","d_s001","d_s002","d_s003","d_s004"],"clarify_field":"district","focus_alias":"","inherited_fields":[],"intent":"none","plan":{"district":{"chamber":"","code":""},"issue_id":"","map_session":0,"service_area_id":"","steps":[]},"reason_code":"missing_context","status":"clarify"}',
 'Q01B': '{"clarify_choices":["c_house","c_senate"],"clarify_field":"district","focus_alias":"","inherited_fields":[],"intent":"none","plan":{"district":{"chamber":"","code":""},"issue_id":"","map_session":0,"service_area_id":"","steps":[]},"reason_code":"missing_context","status":"clarify"}',
}
SENTINEL = {'district': {'chamber': '', 'code': ''}, 'map_session': 0, 'issue_id': '', 'service_area_id': '', 'steps': []}

class Repair1Tests(unittest.TestCase):
    job = map_tests.MapDefaultTests.job
    @classmethod
    def setUpClass(cls): cls.i = Investigation(load_core())

    def request(self, text, confirmed=None, draft='same', focus=None):
        draft = copy.deepcopy(confirmed) if draft == 'same' else draft
        held = confirmed or draft
        return {'schema_version': SCHEMA_VERSION, 'request_id': str(uuid.uuid4()), 'utterance': text, 'context': {
            'case_id': str(uuid.uuid4()), 'branch_id': str(uuid.uuid4()), 'revision': 3, 'snapshot_id': self.i.snapshot_id,
            'operation_version': 'ia-core/1', 'recipe_version': (held['issue_id'] if held else 'custom') + '/1',
            'confirmed_plan': copy.deepcopy(confirmed), 'draft_plan': copy.deepcopy(draft), 'focused_step_id': focus,
            'selected_claim_refs': []}}
    def run_(self, text, decision, confirmed=None, draft='same', focus=None):
        p = prepare_request(self.request(text, confirmed, draft, focus), self.i, 's')
        return convert_decision(p, strict_json(decision) if isinstance(decision, str) else decision, self.i.core)
    def proposal(self, p, intent='replace_plan'):
        return {'status': 'propose', 'intent': intent, 'plan': dict(wire_plan(p), map_session=0), 'focus_alias': '',
                'clarify_field': '', 'clarify_choices': [], 'reason_code': '', 'inherited_fields': []}
    def clarify(self, field, choices):
        return {'status': 'clarify', 'intent': 'none', 'plan': SENTINEL, 'focus_alias': '', 'clarify_field': field,
                'clarify_choices': list(choices), 'reason_code': 'missing_context', 'inherited_fields': []}
    def refused(self, code, *a, **kw):
        with self.assertRaises(LanguageError) as c: self.run_(*a, **kw)
        self.assertEqual(c.exception.code, code)

    # ---------------------------------------------------------------- family 1: explicit district edits (E06, X20)
    def test_e06_literal_move_plan_from_to_is_accepted_and_wrong_geography_still_refused(self):
        u = 'Move this plan from Senate 21 to Senate 22.'
        out = self.run_(u, SAVED['E06'], S21)
        self.assertEqual((out['status'], out['normalized_plan']['district']), ('propose', D('senate', '022')))
        self.assertEqual([x['field'] for x in out['typed_diff']], ['district'])
        for text in ('Change the district from Senate 21 to Senate 22.', 'Switch our plan from SD 21 to SD 22.', 'Move from Senate 21 to Senate 22.'):
            with self.subTest(text=text):
                self.assertEqual(self.run_(text, SAVED['E06'], S21)['normalized_plan']['district'], D('senate', '022'))
        self.refused('explicit_district_conflict', 'Move this plan from Senate 20 to Senate 22.', SAVED['E06'], S21)  # stale source
        self.refused('explicit_district_conflict', u, self.proposal(S21), S21)  # target ignored
        self.refused('explicit_district_conflict', u, self.proposal(plan(D('senate', '023'), S21['steps'])), S21)
        self.refused('explicit_district_conflict', u, SAVED['E06'].replace('replace_plan', 'create_plan'))  # no held plan: source unproven
        # Without replacement wording two districts stay ambiguous (unchanged protection).
        self.refused('explicit_district_ambiguous', 'Profile median age for Senate 21 and Senate 22.', SAVED['E06'], S21)

    def test_x20_literal_focused_step_retarget_is_accepted_only_for_a_focused_compare_step(self):
        u = 'Point this step at Senate 23 instead.'
        out = self.run_(u, SAVED['X20'], S18, focus='s2')
        self.assertEqual(out['normalized_plan']['district'], D('senate', '018'))
        self.assertEqual(out['normalized_plan']['steps'][1]['args']['comparison_geography'], 'HI-SENATE-023-2024')
        self.assertIn('focus', out['inherited_fields'])
        for text in ('Change this comparison to Senate 23.', 'Set the comparator to SD 23.', 'Aim this step at Senate 23.'):
            with self.subTest(text=text):self.assertEqual(self.run_(text, SAVED['X20'], S18, focus='s2')['status'], 'propose')
        # repair-1 v4: with no focus the held plan's ONLY compare step is the visible, unambiguous target; a focused
        # non-compare step, or several compare steps with no focus, fails closed (never primary-district navigation).
        self.assertEqual(self.run_(u, SAVED['X20'], S18)['normalized_plan']['district'], D('senate', '018'))
        self.refused('explicit_step_focus_missing', u, SAVED['X20'], S18, focus='s1')
        two = plan(D('senate', '018'), [*S18['steps'], cmp('HI-COUNTY-003-2024', 'unemployment_rate', sid='s3')])
        self.refused('explicit_step_focus_missing', u, SAVED['X20'], two)
        # The target must land in the focused step, not a new or other step; the held primary may not move.
        added = plan(D('senate', '018'), [*S18['steps'], cmp('HI-SENATE-023-2024', 'unemployment_rate', sid='s3')])
        self.refused('explicit_comparator_conflict', u, self.proposal(added), S18, focus='s2')
        moved = plan(D('senate', '023'), [prof('unemployment_rate'), cmp(STATE, 'unemployment_rate')])
        self.refused('explicit_district_conflict', u, self.proposal(moved), S18, focus='s2')
        wrong = plan(D('senate', '018'), [prof('unemployment_rate'), cmp('HI-SENATE-024-2024', 'unemployment_rate')])
        self.refused('explicit_comparator_conflict', u, self.proposal(wrong), S18, focus='s2')
        house = plan(D('senate', '018'), [prof('unemployment_rate'), cmp('HI-HOUSE-023-2024', 'unemployment_rate')])
        self.refused('explicit_comparator_conflict', u, self.proposal(house), S18, focus='s2')  # wrong chamber

    # ---------------------------------------------------------------- family 2: named recipes (G05, G06)
    def test_recipe_labels_are_the_apps_own_issue_labels(self):
        self.assertEqual({k: v[0] for k, v in RECIPE_LABELS.items()}, {v.rsplit('/', 1)[0]: n for v, n in _ISSUE_NAMES.items() if v != 'custom/1'})
        js = (Path(__file__).resolve().parents[1] / 'static/investigation.js').read_text(encoding='utf-8')
        for issue, names in RECIPE_LABELS.items():
            self.assertIn(f'{issue}: "{names[0]}"', js)
            for name in names:self.assertIn(f'"{name}"', PROMPT)

    def test_g05_literal_lone_lead_for_named_recipe_is_refused_and_the_recipe_is_accepted(self):
        # repair-1 v4: the named recipe is a prompt/catalog default, not a server rule. The literal lone lead is a
        # valid typed proposal again (a model task miss, not a guard defect); the full recipe is accepted.
        u = 'Run SNAP outreach for Senate 23.'
        self.assertEqual(self.run_(u, SAVED['G05'])['normalized_plan']['issue_id'], 'custom')
        out = self.run_(u, self.proposal(food_assistance_recipe(D('senate', '023')), 'create_plan'))
        self.assertEqual((out['normalized_plan']['issue_id'], len(out['normalized_plan']['steps'])), ('food_assistance_outreach', 3))
        # Additions are free; a truncated recipe is refused; reordered metric lists still match.
        extra = food_assistance_recipe(D('senate', '023'));extra['steps'].append(cmp(STATE, 'median_household_income', sid='s4'))
        self.assertEqual(self.run_('Run SNAP outreach for Senate 23 and compare median household income with the State.', self.proposal(extra, 'create_plan'))['status'], 'propose')
        lone = plan(D('senate', '023'), [{'step_id': 's1', 'operation': 'outreach_lead', 'args': {'program_id': 'snap_hi'}}], 'food_assistance_outreach')
        self.assertEqual(self.run_(u, self.proposal(lone, 'create_plan'))['status'], 'propose')
        swapped = food_assistance_recipe(D('senate', '023'));swapped['steps'][0]['args']['metric_ids'].reverse()
        self.assertEqual(self.run_(u, self.proposal(swapped, 'create_plan'))['status'], 'propose')
        # Over a held other issue (the live app always holds a draft) the recipe proposal is accepted.
        self.assertEqual(self.run_(u, self.proposal(food_assistance_recipe(D('senate', '023'))), S21)['normalized_plan']['issue_id'], 'food_assistance_outreach')
        # A held same recipe may be edited freely (no completeness rule); a "SNAP outreach lead" is a step, not the recipe.
        h28 = food_assistance_recipe(D('house', '028'));kept = copy.deepcopy(h28);kept['steps'].pop()
        self.assertEqual(self.run_('Drop the lead from this SNAP outreach plan.', self.proposal(kept), h28)['status'], 'propose')
        lead = plan(D('house', '028'), [prof('median_age'), {'step_id': 's2', 'operation': 'outreach_lead', 'args': {'program_id': 'snap_hi'}}])
        self.assertEqual(self.run_('Add a SNAP outreach lead.', self.proposal(lead), plan(D('house', '028'), [prof('median_age')]))['normalized_plan']['issue_id'], 'custom')
        # Typed utterance-only recoveries still precede the recipe refusal (chamber-only district: complete Senate list).
        out = self.run_('Run SNAP outreach for a senate district.', SAVED['G05'])
        self.assertEqual((out['clarify_field'], len(out['choices']), out['recovered_from']), ('district', 25, 'explicit_district_missing'))
        # A negated recipe name never forces the recipe.
        self.assertEqual(self.run_('Not SNAP outreach; just profile median age for Senate 23.', self.proposal(plan(D('senate', '023'), [prof('median_age')]), 'create_plan'))['status'], 'propose')

    def test_g06_literal_outputs_recipe_accepted_and_program_clarify_is_a_model_choice(self):
        u = 'Set up older-adult support at home for House 4.'
        out = self.run_(u, SAVED['G06B'])
        self.assertEqual((out['status'], out['normalized_plan']['issue_id']), ('propose', 'aging_at_home'))
        out = self.run_(u, SAVED['G06A'])  # generation choice: a valid (unnecessary) clarification; only live runs can change it
        self.assertEqual((out['status'], out['clarify_field'], out.get('recovered_from')), ('clarify', 'program', None))
        self.assertEqual(self.run_('Set up older adult support at home for House 4.', SAVED['G06B'])['status'], 'propose')
        self.assertEqual(self.run_(u, self.proposal(plan(D('house', '004'), [prof('population_65_plus')]), 'create_plan'))['status'], 'propose')  # v4: not forced

    # ---------------------------------------------------------------- family 3: held unsaved draft district (X21, X22)
    def test_x21_x22_held_draft_district_admits_the_followup_and_literal_clarify_is_a_model_choice(self):
        cases = (('X21', 'How does the median household income here stack up against the State?', H25_FOOD, cmp(STATE, 'median_household_income', sid='s4')),
                 ('X22', 'Add a Kauai County comparison for senior poverty.', S12_AGING, cmp('HI-COUNTY-007-2024', 'poverty_rate_65_plus', sid='s5')))
        for cid, u, draft, step in cases:
            with self.subTest(case=cid):
                good = copy.deepcopy(draft);good['steps'].append(step)
                out = self.run_(u, self.proposal(good), None, draft)
                self.assertEqual((out['status'], out['normalized_plan']['district'], out['inherited_fields']), ('propose', draft['district'], []))
                self.assertEqual([x['change'] for x in out['typed_diff']], ['added'])
                out = self.run_(u, SAVED[cid], None, draft)  # the literal one-choice clarification stays the model's own
                self.assertEqual((out['status'], out.get('recovered_from')), ('clarify', None))
                # Protections kept: an unstated district change, and a divergent confirmed/draft pair.
                moved = copy.deepcopy(good);moved['district'] = D('house', '026')
                self.refused('explicit_district_unstated_change', u, self.proposal(moved), None, draft)
                other = copy.deepcopy(draft);other['district'] = D('house', '026')
                out = self.run_(u, self.proposal(good), other, draft)
                self.assertEqual((out['status'], out['clarify_field']), ('clarify', 'control_conflict'))
        self.assertIn('else (no confirmed plan) the unsaved draft_plan', PROMPT)

    # ---------------------------------------------------------------- family 4: progressive missing-district clarification (Q01)
    def test_q01_literal_outputs_get_the_progressive_chamber_clarification(self):
        u = 'I want the unemployment rate for the district I represent.'
        for key in ('Q01A', 'Q01B'):  # arbitrary 8-district subset; wrong-kind field (was invalid_clarification)
            with self.subTest(arm=key):
                out = self.run_(u, SAVED[key])
                self.assertEqual((out['status'], out['clarify_field'], [c['alias'] for c in out['choices']], out['recovered_from']),
                                 ('clarify', 'chamber', ['c_house', 'c_senate'], 'explicit_district_missing'))
        out = self.run_(u, self.clarify('chamber', ['c_senate', 'c_house']))  # the instructed model answer stays its own
        self.assertEqual((out['clarify_field'], out.get('recovered_from')), ('chamber', None))
        guessed = self.proposal(plan(D('house', '001'), [prof('unemployment_rate')]), 'create_plan')
        self.assertEqual(self.run_(u, guessed)['clarify_field'], 'chamber')  # a guessed district is never proposed
        # Stated chamber: that chamber's complete list, whatever partial/wrong-kind answer the model gave.
        for text, model, n, prefix in (('Unemployment rate for my House district.', self.clarify('chamber', ['c_house']), 51, 'd_h'),
                                       ('Unemployment rate for my Senate district.', self.clarify('district', ['d_s001', 'd_s002']), 25, 'd_s'),
                                       ('Senior poverty around Hilo.', self.clarify('district', ['d_h001', 'd_h002', 'd_s001']), 2, 'c_')):
            with self.subTest(text=text):
                choices = [c['alias'] for c in self.run_(text, model)['choices']]
                self.assertEqual(len(choices), n);self.assertTrue(all(a.startswith(prefix) for a in choices))

    def test_missing_district_override_does_not_touch_grounded_or_held_clarifications(self):
        held = plan(D('house', '025'), [prof('median_age')])
        for text, model, ctx in (('Median household income for district 9, please.', self.clarify('chamber', ['c_house', 'c_senate']), None),
                                 ("Show median age for our Senate seat - it's district 1 or 2.", self.clarify('district', ['d_s001', 'd_s002']), None),
                                 ('Show median age for our Senate seat 1 or 2.', self.clarify('district', ['d_s001', 'd_s002']), None),
                                 ('Compare House 5 and House 6.', self.clarify('district', ['d_h005', 'd_h006']), None),
                                 ('How does the median age here compare?', self.clarify('district', ['d_h025']), held)):
            with self.subTest(text=text):
                out = self.run_(text, model, held if ctx else None)
                self.assertEqual((out['clarify_field'], [c['alias'] for c in out['choices']], out.get('recovered_from')),
                                 (model['clarify_field'], model['clarify_choices'], None))
        self.refused('invalid_clarification', 'Median age for district 9.', self.clarify('district', ['c_house']))  # wrong kind, not proven missing
        # repair-1 v4: an ungrounded State district list for non-legislative wording is refused, never re-offered.
        self.refused('nonlegislative_district_unproven', 'Profile my council district.', self.clarify('district', ['d_h001']))
        self.assertNotIn('A missing district clarifies district.', PROMPT)
        self.assertIn('never offer a partial, guessed or place-derived district list', PROMPT.lower())

    def test_job_attribution_for_server_progressive_clarification(self):
        out = self.job(self.request('I want the unemployment rate for the district I represent.'), SAVED['Q01B'])
        self.assertEqual((out['status'], out['clarify_field'], out['attribution']['decision_origin'], out['attribution']['recovery_category']),
                         ('clarify', 'chamber', 'server_recovery', 'missing_district'))
        out = self.job(self.request('Move this plan from Senate 21 to Senate 22.', S21), SAVED['E06'])
        self.assertEqual((out['status'], out['attribution']['decision_origin']), ('propose', 'model'))
        out = self.job(self.request('Run SNAP outreach for Senate 23.'), SAVED['G05'])
        self.assertEqual((out['status'], out['attribution']['decision_origin']), ('propose', 'model'))  # v4: recipe not forced

    def test_prompt_never_asks_for_more_than_eight_choices(self):
        self.assertIn('1-8 clarify_choices', PROMPT)
        self.assertFalse(re.search(r'\b(?:76|51|25)\b[^.]{0,30}\bchoices\b', PROMPT))

if __name__ == '__main__': unittest.main()

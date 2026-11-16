"""Functional tests over the real verified engine (in-process Connector; the wire is covered in test_wire)."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
import unittest
import uuid

from haic_mcp.tests.support import (EIGHT_STEPS, RECIPE_LABEL, Flow, ToolError, connector, engine, local_call,
                                    recipe_steps, size, step, synthetic_decision)
from haic_mcp.tools import MAX_ARGUMENT_BYTES, proposal_digest

UUID4 = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
CONTEXT_KEYS = ['case_id', 'branch_id', 'revision', 'snapshot_id', 'operation_version', 'recipe_version', 'confirmed_plan',
                'draft_plan', 'focused_step_id', 'selected_claim_refs']
SENIOR_Q = 'Compare senior poverty in House 28 with the State.'
EIGHT_Q = ('House 28 full profile, then compare senior poverty, all-people poverty, median household income and senior population '
           'against the State, against Honolulu County and against Senate 25, plus program evidence for SNAP, Med-QUEST, Section 8, '
           'Kupuna Care and WIC, Kupuna Care and SNAP outreach leads, and administrative evidence.')


def eight_step_decision():
    return synthetic_decision(chamber='house', code='028', issue='custom', steps=EIGHT_STEPS + [
        step('s8', 'administrative_evidence', observations=sorted(engine().core.administrative_rows)[:8])])
SENIOR_D = synthetic_decision(chamber='house', code='028', issue='custom',
                              steps=[step('s1', 'compare', ['poverty_rate_65_plus'], 'HI-STATE-2024')])


def code_of(fn):
    try:
        fn()
    except ToolError as exc:
        return exc.code, exc
    raise AssertionError('expected a ToolError')


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = connector()
        cls.call = staticmethod(local_call(cls.conn))
        cls.flow = Flow(cls.call)
        cls.identity = engine().identity

    def recipe_run(self, issue='aging_at_home', chamber='house', code='028'):
        utterance = f'Run the {RECIPE_LABEL[issue]} recipe for {chamber.title()} {int(code)}.'
        return self.flow.ask_and_run(utterance, synthetic_decision(chamber=chamber, code=code, issue=issue, steps=recipe_steps(issue)))


class PrepareTests(Base):
    def test_first_call_blank_context_has_exact_shape_and_no_defaults(self):
        p = self.flow.prepare(SENIOR_Q)
        req = p['request']
        self.assertEqual(list(req), ['schema_version', 'request_id', 'utterance', 'context'])
        self.assertEqual(req['schema_version'], 'ia-language/1')
        self.assertEqual(req['utterance'], SENIOR_Q)
        ctx = req['context']
        self.assertEqual(list(ctx), CONTEXT_KEYS)
        for key in ('case_id', 'branch_id'):
            self.assertRegex(ctx[key], UUID4)
        self.assertRegex(req['request_id'], UUID4)
        self.assertEqual((ctx['revision'], ctx['recipe_version'], ctx['operation_version']), (0, 'custom/1', 'ia-core/1'))
        self.assertEqual(ctx['snapshot_id'], self.identity['engine']['snapshot_id'])
        self.assertEqual((ctx['confirmed_plan'], ctx['draft_plan'], ctx['focused_step_id'], ctx['selected_claim_refs']), (None, None, None, []))
        self.assertEqual(p['next_context'], ctx)
        text = json.dumps(p, ensure_ascii=False)
        self.assertNotIn('default_plan', text)
        self.assertNotIn('default_plan', json.dumps(self.identity))
        pc = p['provider_context']
        self.assertEqual((pc['confirmed_plan'], pc['draft_plan'], pc['selected']), (None, None, {}))
        self.assertTrue(all('district' not in r for r in pc['catalog']['recipe_plans']))
        self.assertIn('validate_proposal', p['interpretation_rules'])
        self.assertTrue(p['interpretation_rules'].startswith('INTERPRETATION PHASE RULES.'))
        self.assertEqual(p['interpretation_rules_sha256'], 'sha256:' + hashlib.sha256(p['interpretation_rules'].encode()).hexdigest())
        # Internal choice maps and alias-to-reference tables are not dumped.
        self.assertNotIn('choices', p)
        self.assertNotIn('aliases', p)
        self.assertEqual(p['decision_schema']['properties']['status']['enum'], ['propose', 'clarify', 'unsupported', 'uncertain'])

    def test_fresh_ids_each_first_call(self):
        a, b = self.flow.prepare(SENIOR_Q), self.flow.prepare(SENIOR_Q)
        self.assertNotEqual(a['request']['request_id'], b['request']['request_id'])
        self.assertNotEqual(a['request']['context']['case_id'], b['request']['context']['case_id'])
        strip = lambda p: {k: v for k, v in p.items() if k not in ('request', 'next_context')}
        self.assertEqual(strip(a), strip(b))  # everything except minted IDs is stable

    def test_followup_preserves_ids_and_increments_revision(self):
        p, v, r = self.flow.ask_and_run(SENIOR_Q, SENIOR_D)
        nxt = r['next_context']
        f = self.flow.prepare('Add the all-people poverty rate to that comparison.', nxt, p['identity'])
        ctx = f['request']['context']
        self.assertEqual((ctx['case_id'], ctx['branch_id']), (nxt['case_id'], nxt['branch_id']))
        self.assertEqual(ctx['revision'], nxt['revision'] + 1)
        self.assertNotEqual(f['request']['request_id'], p['request']['request_id'])
        self.assertEqual(f['provider_context']['confirmed_plan']['district'], {'chamber': 'house', 'code': '028'})
        # Re-validation of the returned request does not allocate IDs or advance the revision.
        d = synthetic_decision(intent='replace_plan', chamber='house', code='028', issue='custom', inherited=['district'],
                               steps=[step('s1', 'compare', ['poverty_rate_65_plus', 'poverty_rate_all_people'], 'HI-STATE-2024')])
        v2 = self.flow.validate(f, d)
        self.assertEqual(v2['status'], 'propose', v2)
        self.assertEqual(v2['request'], f['request'])
        self.assertEqual(v2['next_context'], f['request']['context'])

    def test_followup_requires_identity_and_bounded_revision(self):
        p = self.flow.prepare(SENIOR_Q)
        self.assertEqual(code_of(lambda: self.call('prepare_question', {'utterance': 'And for seniors?', 'context': p['next_context']}))[0], 'identity_required')
        ctx = dict(p['next_context'], revision=2147483647)
        self.assertEqual(code_of(lambda: self.flow.prepare('Again.', ctx, p['identity']))[0], 'revision_exhausted')
        wrong = copy.deepcopy(p['identity'])
        wrong['engine']['snapshot_id'] = 'sha256:' + '0' * 64
        self.assertEqual(code_of(lambda: self.flow.prepare('Again.', p['next_context'], wrong))[0], 'identity_mismatch')
        self.assertEqual(code_of(lambda: self.call('prepare_question', {'utterance': SENIOR_Q, 'expected_identity': wrong}))[0], 'identity_mismatch')

    def test_context_snapshot_drift_is_typed(self):
        p = self.flow.prepare(SENIOR_Q)
        ctx = dict(p['next_context'], snapshot_id='sha256:' + '1' * 64)
        code, exc = code_of(lambda: self.flow.prepare('Again.', ctx, p['identity']))
        self.assertEqual((code, exc.extra['engine_code']), ('context_rejected', 'snapshot_unavailable'))


class GuardTests(Base):
    """Novel guard cases written for this adapter (not the engine's reserved evaluation cases)."""

    def outcome(self, utterance, decision):
        v = self.flow.validate(self.flow.prepare(utterance), decision)
        return v['status'], v['rejection_code'], (v['recovery'] or {}).get('code'), v['clarify_field'], [c['alias'] for c in v['choices']], v

    def test_directed_comparator_order_is_enforced(self):
        q = 'How does senior poverty in House 9 look against Senate 3?'
        swapped = synthetic_decision(chamber='senate', code='003', issue='custom', steps=[step('s1', 'compare', ['poverty_rate_65_plus'], 'HI-HOUSE-009-2024')])
        self.assertEqual(self.outcome(q, swapped)[:2], ('uncertain', 'explicit_district_conflict'))
        self.assertIsNone(self.outcome(q, swapped)[5]['proposal_digest'])
        right = synthetic_decision(chamber='house', code='009', issue='custom', steps=[step('s1', 'compare', ['poverty_rate_65_plus'], 'HI-SENATE-003-2024')])
        status, *_, v = self.outcome(q, right)
        self.assertEqual(status, 'propose')
        self.assertEqual(v['normalized_plan']['district']['code'], '009')

    def test_no_default_district_is_inferred(self):
        guessed = synthetic_decision(chamber='house', code='028', issue='custom', steps=[step('s1', 'profile', ['poverty_rate_65_plus'])])
        for q in ('What is the senior poverty rate?', 'What is the senior poverty rate in my district?'):
            status, _, recovered, field, choices, v = self.outcome(q, guessed)
            self.assertEqual((status, recovered, field, choices), ('clarify', 'explicit_district_missing', 'chamber', ['c_house', 'c_senate']), q)
            self.assertIsNone(v['normalized_plan'])

    def test_bare_number_and_nonlegislative_and_comparator_guards(self):
        q = 'Show seniors living alone in district 7.'
        d = synthetic_decision(chamber='house', code='007', issue='custom', steps=[step('s1', 'profile', ['male_householder_65_plus_living_alone'])])
        self.assertEqual(self.outcome(q, d)[2:5], ('explicit_district_missing', 'district', ['d_h007', 'd_s007']))
        d = synthetic_decision(chamber='house', code='002', issue='custom', steps=[step('s1', 'profile')])
        self.assertEqual(self.outcome("Profile Hawaii's 2nd congressional district.", d)[:3], ('unsupported', None, 'nonlegislative_district'))
        d = synthetic_decision(chamber='house', code='040', issue='custom', steps=[step('s1', 'compare', ['median_household_income'], 'HI-HOUSE-041-2024')])
        self.assertEqual(self.outcome("Compare House 40's median household income with a neighboring district.", d)[:2], ('uncertain', 'explicit_comparator_unstated'))

    def test_unsupported_inference_and_cross_measure_and_program_theme(self):
        d = synthetic_decision(chamber='house', code='022', issue='custom', steps=[step('s1', 'compare', ['median_household_income', 'poverty_rate_all_people'], 'HI-STATE-2024')])
        self.assertEqual(self.outcome('Compare median household income against poverty in House 22.', d)[:3], ('unsupported', None, 'unsupported_cross_measure'))
        d = synthetic_decision(chamber='senate', code='012', issue='custom', steps=[step('s1', 'program_evidence', programs=['snap_hi'])])
        self.assertEqual(self.outcome('Which residents of Senate 12 are eligible for SNAP?', d)[:3], ('unsupported', None, 'unsupported_explicit_constraint'))
        d = synthetic_decision(chamber='house', code='033', issue='custom', steps=[step('s1', 'program_evidence', programs=['snap_hi'])])
        self.assertEqual(self.outcome('Show food assistance programs for House 33.', d)[2:5], ('ungrounded_program', 'program', ['p_snap_hi', 'p_wic_hi']))

    def test_release_guards_significance_and_coordinated_comparators(self):
        d = synthetic_decision(chamber='house', code='031', issue='custom', steps=[step('s1', 'compare', ['poverty_rate_65_plus'], 'HI-STATE-2024')])
        self.assertEqual(self.outcome('Is senior poverty in House 31 significantly higher than the State?', d)[:3],
                         ('unsupported', None, 'unsupported_explicit_constraint'))
        d = synthetic_decision(chamber='house', code='031', issue='custom', steps=[step('s1', 'compare', ['poverty_rate_65_plus'], 'HI-HOUSE-006-2024')])
        self.assertEqual(self.outcome('Compare senior poverty in House 31 with House 6 and Senate 14.', d)[:2], ('uncertain', 'explicit_comparator_conflict'))

    def test_map_year_boundary_and_canonical_decision(self):
        q = 'Use the 2024 map for a senior poverty profile of House 17.'
        as_float = synthetic_decision(chamber='house', code='017', issue='custom', map_session=2024.0, steps=[step('s1', 'profile', ['poverty_rate_65_plus'])])
        as_int = dict(as_float, plan=dict(as_float['plan'], map_session=2024))
        p = self.flow.prepare(q)
        vf, vi = self.flow.validate(p, as_float), self.flow.validate(p, as_int)
        self.assertEqual(vf['status'], 'propose')
        self.assertIs(type(vf['decision']['plan']['map_session']), int)
        self.assertEqual(vf['decision'], vi['decision'])
        self.assertEqual(vf['proposal_digest'], vi['proposal_digest'])
        self.assertEqual(vf['normalized_plan']['map_session'], 2024)
        # The float form copied back still runs (same canonical digest); a different decision never shares it.
        self.assertEqual(self.flow.run(dict(vf, decision=as_float))['run_status'], 'ok')
        other = dict(as_int, plan=dict(as_int['plan'], steps=[step('s1', 'profile', ['poverty_rate_all_people'])]))
        self.assertNotEqual(self.flow.validate(p, other)['proposal_digest'], vf['proposal_digest'])
        fractional = dict(as_float, plan=dict(as_float['plan'], map_session=2024.5))
        self.assertEqual(code_of(lambda: self.flow.validate(p, fractional))[0], 'decision_schema_mismatch')
        wrong_year = dict(as_int, plan=dict(as_int['plan'], map_session=2026))
        self.assertEqual(self.flow.validate(p, wrong_year)['rejection_code'], 'explicit_map_conflict')


class DigestTests(Base):
    def test_digest_formula_is_the_documented_canonical_json(self):
        p = self.flow.prepare(SENIOR_Q)
        v = self.flow.validate(p, SENIOR_D)
        validated = {k: v[k] for k in ('status', 'intent', 'message', 'reason_code', 'normalized_plan', 'typed_diff', 'inherited_fields',
                                        'source_inspection_refs', 'choices', 'clarify_field', 'recovery', 'rejection_code')}
        named = {'proposal_digest_version': 'haic-mcp-proposal/1', 'request': p['request'], 'decision': SENIOR_D,
                 'validated': validated, 'expected_identity': self.identity}
        raw = json.dumps(named, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.assertEqual(v['proposal_digest'], 'sha256:' + hashlib.sha256(raw).hexdigest())
        self.assertEqual(v['proposal_digest'], proposal_digest(p['request'], SENIOR_D, validated, self.identity))
        self.assertEqual(self.flow.validate(p, SENIOR_D), v)  # deterministic

    def test_changed_inputs_with_old_digest_are_rejected(self):
        p = self.flow.prepare(SENIOR_Q)
        v = self.flow.validate(p, SENIOR_D)
        good = Flow.bundle(v)
        changed_utterance = copy.deepcopy(good)
        changed_utterance['request']['utterance'] = 'Compare senior poverty in House 29 with the State.'
        changed_decision = copy.deepcopy(good)
        changed_decision['decision']['plan']['steps'][0]['metric_ids'] = ['poverty_rate_all_people']
        changed_context = copy.deepcopy(good)
        changed_context['request']['context']['case_id'] = str(uuid.uuid4())
        for bundle in (changed_utterance, changed_decision, changed_context):
            self.assertEqual(code_of(lambda: self.call('run_plan', bundle))[0], 'proposal_digest_mismatch')
        changed_identity = copy.deepcopy(good)
        changed_identity['expected_identity']['connector']['build_digest'] = 'sha256:' + '2' * 64
        self.assertEqual(code_of(lambda: self.call('run_plan', changed_identity))[0], 'identity_mismatch')
        self.assertEqual(self.call('run_plan', good)['run_status'], 'ok')

    def test_bare_plan_and_partial_bundles_are_rejected(self):
        p = self.flow.prepare(SENIOR_Q)
        v = self.flow.validate(p, SENIOR_D)
        bare = dict(Flow.bundle(v), plan=v['normalized_plan'])
        self.assertEqual(code_of(lambda: self.call('run_plan', bare))[0], 'invalid_arguments')
        no_digest = {k: x for k, x in Flow.bundle(v).items() if k != 'proposal_digest'}
        self.assertEqual(code_of(lambda: self.call('run_plan', no_digest))[0], 'invalid_arguments')
        # A clarification has nothing executable even with its own digest.
        q = self.flow.prepare('What is the senior poverty rate?')
        c = self.flow.validate(q, synthetic_decision(status='clarify', intent='none', field='chamber', choices=['c_house', 'c_senate'], reason='missing_context'))
        self.assertEqual(c['status'], 'clarify')
        self.assertEqual(code_of(lambda: self.call('run_plan', Flow.bundle(c)))[0], 'not_applicable')

    def test_invalid_static_and_dynamic_objects(self):
        p = self.flow.prepare(SENIOR_Q)
        bad_request = copy.deepcopy(p['request'])
        bad_request['context']['extra'] = 1
        self.assertEqual(code_of(lambda: self.call('validate_proposal', {'request': bad_request, 'decision': SENIOR_D, 'expected_identity': self.identity}))[0], 'invalid_arguments')
        missing_field = {k: x for k, x in SENIOR_D.items() if k != 'focus_alias'}
        self.assertEqual(code_of(lambda: self.flow.validate(p, missing_field))[0], 'decision_schema_mismatch')
        unknown_metric = copy.deepcopy(SENIOR_D)
        unknown_metric['plan']['steps'][0]['metric_ids'] = ['made_up_metric']
        self.assertEqual(code_of(lambda: self.flow.validate(p, unknown_metric))[0], 'decision_schema_mismatch')
        self.assertEqual(code_of(lambda: self.call('validate_proposal', {'request': p['request'], 'decision': [], 'expected_identity': self.identity}))[0], 'invalid_arguments')
        self.assertEqual(code_of(lambda: self.call('prepare_question', {'utterance': 'x' * 501}))[0], 'invalid_arguments')
        self.assertEqual(code_of(lambda: self.call('prepare_question', {'utterance': 'See https://example.org'}))[1].extra['engine_code'], 'utterance_not_admitted')
        self.assertEqual(code_of(lambda: self.call('no_such_tool', {}))[0], 'unknown_tool')
        self.assertEqual(code_of(lambda: self.call('prepare_question', {'utterance': 'a', 'x': float('nan')}))[0], 'invalid_arguments')
        big = {'utterance': 'Compare.', 'context': None, 'expected_identity': {'pad': 'y' * MAX_ARGUMENT_BYTES}}
        self.assertEqual(code_of(lambda: self.call('prepare_question', big))[0], 'arguments_too_large')


class RunAndContextTests(Base):
    def test_successful_run_promotes_plan_and_keeps_only_retained_selections(self):
        p, v, r = self.flow.ask_and_run(SENIOR_Q, SENIOR_D)
        nxt = r['next_context']
        self.assertEqual(list(nxt), CONTEXT_KEYS)
        self.assertEqual(nxt['confirmed_plan'], v['normalized_plan'])
        self.assertEqual(nxt['draft_plan'], v['normalized_plan'])
        self.assertEqual(nxt['recipe_version'], 'custom/1')
        self.assertEqual(nxt['selected_claim_refs'], [])  # new claims stay unselected
        self.assertEqual({k: nxt[k] for k in ('case_id', 'branch_id', 'revision', 'snapshot_id')},
                         {k: p['request']['context'][k] for k in ('case_id', 'branch_id', 'revision', 'snapshot_id')})
        cmp_ref = next(c['claim_ref'] for c in r['claims'] if c['kind'] == 'comparison')
        house_ref = next(c['claim_ref'] for c in r['claims'] if c['finding_id'].startswith('stat:HI-HOUSE-028'))
        ctx = dict(nxt, selected_claim_refs=[cmp_ref, house_ref], focused_step_id='s1')
        # Retarget the comparison to a county: the State comparison is retired; the House 28 statistic is retained.
        q = 'Point this comparison at Honolulu County instead.'
        f = self.flow.prepare(q, ctx, p['identity'])
        d = synthetic_decision(intent='replace_plan', chamber='house', code='028', issue='custom', inherited=['district'],
                               steps=[step('s1', 'compare', ['poverty_rate_65_plus'], 'HI-COUNTY-003-2024')])
        v2 = self.flow.validate(f, d)
        self.assertEqual(v2['status'], 'propose', v2)
        r2 = self.flow.run(v2)
        self.assertEqual([(x['state'], x['reason_code']) for x in r2['selection_review']],
                         [('retired', 'comparison_not_in_current_steps'), ('retained', 'exact_canonical_identity')])
        self.assertEqual(r2['next_context']['selected_claim_refs'], [house_ref])
        self.assertEqual(r2['next_context']['focused_step_id'], 's1')
        self.assertEqual(r2['next_context']['revision'], f['request']['context']['revision'])

    def test_partial_run_is_not_promoted_and_context_recovers(self):
        q = 'Draft a Section 8 outreach lead and a full profile for House 1.'
        d = synthetic_decision(chamber='house', code='001', issue='custom', steps=[step('s1', 'outreach_lead', programs=['hcv_honolulu']), step('s2', 'profile')])
        p, v, r = self.flow.ask_and_run(q, d)
        self.assertEqual(r['run_status'], 'partial')
        self.assertEqual([s['status'] for s in r['steps']], ['unsupported', 'ok'])
        self.assertTrue(r['steps'][0]['message'])
        self.assertTrue(r['claims'])  # independent results remain available
        nxt = r['next_context']
        self.assertEqual((nxt['confirmed_plan'], nxt['draft_plan'], nxt['selected_claim_refs'], nxt['recipe_version']),
                         (None, v['normalized_plan'], [], 'custom/1'))
        follow = self.flow.prepare('Drop the Section 8 lead.', nxt, p['identity'])  # the next preparation is accepted
        self.assertEqual(follow['provider_context']['draft_plan']['steps'][0]['operation'], 'outreach_lead')
        # After a confirmed plan exists, a partial attempt keeps it and its selections.
        p2, v2, ok = self.flow.ask_and_run('Profile House 1.', synthetic_decision(chamber='house', code='001', issue='custom', steps=[step('s1', 'profile')]))
        pick = ok['claims'][0]['claim_ref']
        ctx = dict(ok['next_context'], selected_claim_refs=[pick])
        f = self.flow.prepare('Also draft a Section 8 outreach lead.', ctx, p2['identity'])
        d2 = synthetic_decision(intent='replace_plan', chamber='house', code='001', issue='custom', inherited=['district'],
                                steps=[step('s1', 'profile'), step('s2', 'outreach_lead', programs=['hcv_honolulu'])])
        v3 = self.flow.validate(f, d2)
        self.assertEqual(v3['status'], 'propose', v3)
        r3 = self.flow.run(v3)
        self.assertEqual(r3['run_status'], 'partial')
        n3 = r3['next_context']
        self.assertEqual((n3['confirmed_plan'], n3['draft_plan'], n3['selected_claim_refs']), (ok['next_context']['confirmed_plan'], v3['normalized_plan'], [pick]))
        # The diverging draft now needs the engine's control-conflict clarification, not a silent choice.
        f2 = self.flow.prepare('Run it.', n3, p2['identity'])
        self.assertTrue(f2['provider_context']['control_conflict'])

    def test_confirmed_plan_that_fails_reprepare_is_a_typed_context_error(self):
        p = self.flow.prepare('Draft a Section 8 outreach lead and a full profile for House 1.')
        broken = {'district': {'state_fips': '15', 'chamber': 'house', 'code': '001', 'boundary_session': 2024}, 'map_session': 2026,
                  'issue_id': 'custom', 'service_area_id': None,
                  'steps': [{'step_id': 's1', 'operation': 'outreach_lead', 'args': {'program_id': 'hcv_honolulu'}}]}
        ctx = dict(p['next_context'], confirmed_plan=broken, draft_plan=broken)
        code, exc = code_of(lambda: self.flow.prepare('Again.', ctx, p['identity']))
        self.assertEqual((code, exc.extra['engine_code'], exc.retry_action), ('context_rejected', 'stale_selection', 'clear_selected_claim_refs_or_start_new_question'))
        malformed = dict(p['next_context'], confirmed_plan={'district': 'House 1'})
        self.assertEqual(code_of(lambda: self.flow.prepare('Again.', malformed, p['identity']))[0], 'context_rejected')

    def test_foreign_and_stale_selections(self):
        p, v, r = self.flow.ask_and_run(SENIOR_Q, SENIOR_D)
        _, _, other = self.flow.ask_and_run('Profile Senate 4.', synthetic_decision(chamber='senate', code='004', issue='custom', steps=[step('s1', 'profile', ['poverty_rate_65_plus'])]))
        foreign = other['claims'][0]['claim_ref']
        ctx = dict(r['next_context'], selected_claim_refs=[foreign])
        self.assertEqual(code_of(lambda: self.flow.prepare('Why that figure?', ctx, p['identity']))[1].extra['engine_code'], 'stale_selection')
        bundle = Flow.bundle(v)
        self.assertEqual(code_of(lambda: self.call('build_brief', dict(bundle, selected_claim_refs=[foreign])))[0], 'foreign_context')
        stale = dict(r['claims'][0]['claim_ref'], snapshot_id='sha256:' + '3' * 64)
        self.assertEqual(code_of(lambda: self.call('build_brief', dict(bundle, selected_claim_refs=[stale])))[0], 'selection_conflict')
        tampered = dict(r['claims'][0]['claim_ref'], semantic_hash='sha256:' + '4' * 64)
        self.assertEqual(code_of(lambda: self.call('inspect_source', dict(bundle, mode='claim', claim_ref=tampered)))[0], 'claim_not_current')
        self.assertEqual(code_of(lambda: self.call('inspect_source', dict(bundle, mode='claim', claim_ref=foreign)))[0], 'claim_not_current')

    def test_eight_step_projection_preserves_required_evidence(self):
        d = eight_step_decision()
        p = self.flow.prepare(EIGHT_Q)
        v = self.flow.validate(p, d)
        self.assertEqual(v['status'], 'propose', v)
        r = self.flow.run(v)
        direct = engine().investigation.handle({'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1', 'recipe_version': 'custom/1',
                                                'snapshot_id': engine().investigation.snapshot_id, 'request_id': p['request']['request_id'],
                                                **{k: p['request']['context'][k] for k in ('case_id', 'branch_id', 'revision')}, 'mode': 'run',
                                                'plan': v['normalized_plan'], 'selected_claim_refs': [], 'selected_action_ref': None})
        self.assertEqual(len(r['steps']), 8)
        self.assertEqual([c['claim_ref'] for c in r['claims']], [c['claim_ref'] for c in direct['claims']])
        caveats = {c['id']: c['text'] for c in r['caveats']}
        for proj, raw in zip(r['claims'], direct['claims']):
            self.assertEqual(proj['text'], raw['text'])
            self.assertEqual([caveats[i] for i in proj['caveat_ids']], raw['limitations'])
            self.assertEqual(proj['dependency_finding_ids'], [x['finding_id'] for x in raw['dependencies']])
            self.assertEqual(set(proj['source_ids']), {x['source_id'] for x in raw['source_inspection_refs']})
            if raw['kind'] == 'statistic':
                for key in ('estimate', 'estimate_display', 'margin_of_error', 'moe_display', 'moe_confidence_level', 'annotation', 'moe_annotation', 'unit', 'universe'):
                    self.assertEqual(proj[key], raw[key], key)
                self.assertEqual(proj['period_label'], raw['period']['label'])
                self.assertEqual(proj['geography']['boundary_session'], raw['geography']['boundary_session'])
                self.assertEqual(proj['source']['locator'], raw['source']['locator'])
            elif raw['kind'] == 'comparison':
                self.assertEqual((proj['difference'], proj['not_differenced_reason'], proj['left_finding_id'], proj['right_finding_id']),
                                 (raw['difference'], raw['not_differenced_reason'], raw['left']['finding_id'], raw['right']['finding_id']))
            elif raw['kind'] == 'administrative_context':
                for key in ('value', 'unit', 'period', 'geography', 'coverage', 'status', 'district_gap_usable', 'suppression'):
                    self.assertEqual(proj[key], raw[key], key)
            elif raw['kind'] == 'program_relevance':
                self.assertEqual((proj['access'], proj['referral'], proj['missing_facts'], proj['eligibility_area']),
                                 (raw['access'], raw['program']['referral'], raw['program']['missing_facts'], raw['eligibility_area']))
                self.assertEqual(proj['related_observations'], raw['relevance']['related_observations'])
                self.assertEqual(proj['criteria_summary'], raw['program']['criteria_summary'])
            elif raw['kind'] == 'outreach_hypothesis':
                self.assertEqual((proj['unknowns'], proj['next_step'], proj['label']), (raw['unknowns'], raw['next_step'], raw['label']))
        self.assertEqual([caveats[i] for i in r['limitation_ids']], direct['limitations'])
        self.assertEqual([x['action_ref'] for x in r['responses']], [x['action_ref'] for x in direct['responses']])
        self.assertEqual([s['finding_ids'] for s in r['steps']], [[x['finding_id'] for x in s['claim_refs']] for s in direct['steps']])
        self.assertLess(size(r), size(direct) / 2)

    def test_program_claims_keep_related_observations_and_criteria(self):
        p, v, r = self.recipe_run('aging_at_home', 'house', '028')
        direct = engine().investigation.handle({'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1',
                                                'recipe_version': 'aging_at_home/1', 'snapshot_id': engine().investigation.snapshot_id,
                                                'request_id': p['request']['request_id'],
                                                **{k: p['request']['context'][k] for k in ('case_id', 'branch_id', 'revision')}, 'mode': 'run',
                                                'plan': v['normalized_plan'], 'selected_claim_refs': [], 'selected_action_ref': None})
        raw = next(c for c in direct['claims'] if c['finding_id'] == 'prog:kupuna_care_hi@HI-HOUSE-028-2024')
        proj = next(c for c in r['claims'] if c['finding_id'] == raw['finding_id'])
        self.assertEqual(len(raw['relevance']['related_observations']), 4)
        self.assertEqual(proj['related_observations'], raw['relevance']['related_observations'])
        self.assertEqual(proj['criteria_summary'], raw['program']['criteria_summary'])
        for obs in proj['related_observations']:  # each carries its estimate and MOE display
            self.assertTrue(obs['estimate_display'] and obs['moe_display'])

    def test_repeat_results_are_stable(self):
        p = self.flow.prepare(SENIOR_Q)
        v = self.flow.validate(p, SENIOR_D)
        self.assertEqual(self.flow.run(v), self.flow.run(v))
        self.assertEqual(self.conn.call('run_plan', Flow.bundle(v))[1], self.conn.call('run_plan', Flow.bundle(v))[1])


class SourceTests(Base):
    def test_source_wire_scenario_comparison_and_hypothesis(self):
        p, v, r = self.recipe_run('aging_at_home', 'house', '028')
        by_kind = {c['kind']: c for c in r['claims']}
        for kind in ('comparison', 'outreach_hypothesis'):
            claim = by_kind[kind]
            ctx = dict(r['next_context'], selected_claim_refs=[claim['claim_ref']])
            f = self.flow.prepare('Why that figure?', ctx, p['identity'])
            self.assertEqual(f['provider_context']['selected']['selected_1']['kind'], kind)
            d = synthetic_decision(intent='inspect_source', focus='selected_1')
            sv = self.flow.validate(f, d)
            self.assertEqual((sv['status'], sv['intent'], sv['normalized_plan']), ('propose', 'inspect_source', None))
            refs = sv['source_inspection_refs']
            self.assertTrue(refs and all(not x['finding_id'].startswith(('cmp:', 'lead:')) for x in refs))
            raw_claim = next(c for c in engine().investigation.handle({**{k: v for k, v in Flow.bundle(v)['request']['context'].items() if k in ('case_id', 'branch_id', 'revision')},
                'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1', 'recipe_version': 'aging_at_home/1', 'snapshot_id': engine().investigation.snapshot_id,
                'request_id': p['request']['request_id'], 'mode': 'run', 'plan': v['normalized_plan'], 'selected_claim_refs': [], 'selected_action_ref': None})['claims']
                if c['claim_ref'] == claim['claim_ref'])
            self.assertEqual(refs, raw_claim['source_inspection_refs'])
            out = self.call('inspect_source', dict(Flow.bundle(sv), mode='source_intent'))
            self.assertEqual(out['references'], refs)
            self.assertEqual([(x['source_id'], x['finding_id']) for x in out['leaves']], [(x['source_id'], x['finding_id']) for x in refs])
            self.assertEqual(out['next_context'], f['request']['context'])
            if kind == 'comparison':
                self.assertEqual({x['finding_id'].split(':')[1] for x in refs}, {'HI-HOUSE-028-2024', 'HI-STATE-2024'})
            else:  # hypothesis: observed need, its State reference and the program reference
                ids = {x['finding_id'] for x in refs}
                self.assertIn('stat:HI-STATE-2024:poverty_rate_65_plus', ids)
                self.assertTrue(any(i.startswith('prog:kupuna_care_hi@') for i in ids))
            one = refs[0]['source_id']
            filtered = self.call('inspect_source', dict(Flow.bundle(sv), mode='source_intent', source_id=one))
            self.assertEqual({x['source_id'] for x in filtered['leaves']}, {one})
            self.assertEqual(code_of(lambda: self.call('inspect_source', dict(Flow.bundle(sv), mode='source_intent', source_id='hi_wic_rules')))[0], 'source_not_in_reference')
            claim_mode = self.call('inspect_source', dict(Flow.bundle(v), mode='claim', claim_ref=claim['claim_ref']))
            self.assertEqual(claim_mode['references'], refs)
            self.assertEqual(claim_mode['next_context'], r['next_context'])
            self.assertEqual(code_of(lambda: self.call('inspect_source', dict(Flow.bundle(sv), mode='claim', claim_ref=claim['claim_ref'])))[0], 'not_applicable')

    def test_explicit_catalog_source_alias(self):
        p = self.flow.prepare('What is source dbedt_2024_state?')
        alias = next(s['alias'] for s in p['provider_context']['catalog']['sources'] if s['source_id'] == 'dbedt_2024_state')
        v = self.flow.validate(p, synthetic_decision(intent='inspect_source', focus=alias))
        self.assertEqual(v['source_inspection_refs'], [{'source_id': 'dbedt_2024_state'}])
        out = self.call('inspect_source', dict(Flow.bundle(v), mode='source_intent'))
        self.assertEqual(out['leaves'], [{'source_id': 'dbedt_2024_state', 'finding_id': None, 'detail': None}])

    def test_canonical_projection_preserves_evidence_and_caveats(self):
        p, v, r = self.flow.ask_and_run(SENIOR_Q, SENIOR_D)
        cmp_claim = next(c for c in r['claims'] if c['kind'] == 'comparison')
        out = self.call('inspect_source', dict(Flow.bundle(v), mode='claim', claim_ref=cmp_claim['claim_ref']))
        core = engine().core
        for leaf in out['leaves']:
            fid = leaf['finding_id']
            canonical = core.finding(fid)
            self.assertEqual(out['normalized_findings'][fid], canonical)
            for key in ('estimate', 'margin_of_error', 'moe_display', 'unit', 'universe', 'period', 'geography', 'moe_confidence_level'):
                self.assertEqual(out['normalized_findings'][fid][key], canonical[key])
            detail = leaf['detail']
            self.assertEqual((detail['verification_kind'], detail['cell_verified'], detail['origin_bytes_available']), ('normalized_projection', False, False))
            self.assertIn('does not reread', detail['verification_note'])
            self.assertEqual(detail['locator'], canonical['source']['locator'])
        for sid, src in out['sources'].items():
            self.assertEqual(src['retained_file']['verification_scope'], 'normalized_projection')
            self.assertFalse(src['retained_file']['available'])
            self.assertEqual(src['source'], core.packet.sources[sid])
            full = core.source(sid)['cited_by']
            self.assertEqual(src['cited_by_counts'], {k: len(x) for k, x in full.items()})
        self.assertEqual(out['fetch_policy'], core.packet.fetch_policy)

    def test_catalog_mode_is_closed(self):
        out = self.call('inspect_source', {'mode': 'catalog', 'expected_identity': self.identity, 'source_id': 'hi_snap_rules'})
        self.assertEqual((out['next_context'], out['leaves'][0]['detail']), (None, None))
        self.assertNotIn('cited_by', out['sources']['hi_snap_rules'])
        p = self.flow.prepare(SENIOR_Q)
        v = self.flow.validate(p, SENIOR_D)
        mixed = dict(Flow.bundle(v), mode='catalog', source_id='hi_snap_rules')
        self.assertEqual(code_of(lambda: self.call('inspect_source', mixed))[0], 'invalid_arguments')  # never downgraded to catalog
        partial = {k: x for k, x in Flow.bundle(v).items() if k != 'proposal_digest'}
        self.assertEqual(code_of(lambda: self.call('inspect_source', dict(partial, mode='source_intent')))[0], 'invalid_arguments')
        self.assertEqual(code_of(lambda: self.call('inspect_source', {'mode': 'catalog', 'expected_identity': self.identity}))[0], 'invalid_arguments')
        self.assertEqual(code_of(lambda: self.call('inspect_source', {'mode': 'catalog', 'expected_identity': self.identity, 'source_id': 'nope'}))[0], 'source_unavailable')
        self.assertEqual(code_of(lambda: self.call('inspect_source', {'mode': 'catalog', 'expected_identity': self.identity, 'source_id': '../etc'}))[0], 'invalid_arguments')


class BriefTests(Base):
    def test_brief_parity_staff_shapes_and_numbered_citations(self):
        p, v, r = self.recipe_run('aging_at_home', 'senate', '010')
        picks = [c['claim_ref'] for c in r['claims'] if c['kind'] in ('comparison', 'outreach_hypothesis')][:2]
        action = r['responses'][0]['action_ref']
        seen = []
        original = engine().investigation.handle

        def spy(envelope):
            seen.append(copy.deepcopy(envelope))
            return original(envelope)
        engine().investigation.handle = spy
        try:
            structured, text = self.conn.call('build_brief', dict(Flow.bundle(v), selected_claim_refs=picks, selected_action_ref=action))
        finally:
            engine().investigation.handle = original
        env = seen[-1]
        self.assertEqual((env['mode'], env['staff_edits'], env['checklist_edits'], env['tracking'], env['edits_reviewed_for']), ('brief', {}, [], None, None))
        direct = original(copy.deepcopy(env))['brief']
        brief = structured['brief']
        self.assertEqual(brief, {k: x for k, x in direct.items() if k != 'html'})
        self.assertNotIn('html', brief)
        self.assertEqual((brief['staff_edits'], brief['tracking'], brief['title_is_staff_edit']), ({}, None, False))
        self.assertTrue(all(not row['staff_edited'] for row in brief['checklist']))
        self.assertEqual(structured['next_context']['selected_claim_refs'], picks)
        for en in brief['entries']:
            self.assertIn(en['text'] + ' ' + ''.join(f'[{n}]' for n in sorted(en['citations'])), text)
        for c in brief['citations']:
            self.assertIn(f"[{c['n']}] {c['publisher']} — {c['source_id']}. {c['url']}", text)
            for loc in c['locators']:
                self.assertIn(loc, text)
        from districtbrief import render
        for limit in render.printed_limitations(brief):
            self.assertIn('- ' + limit, text)
        for fact in brief['action']['facts_to_verify']:
            self.assertIn('- ' + fact, text)
        self.assertIn(''.join(f'[{n}]' for n in sorted(brief['action_citations'])), text)
        self.assertIsNone(re.search(r'</?[a-z][^>]*>', text))  # readable text, not HTML

    def test_brief_rejects_staff_inputs_and_unknown_actions(self):
        p, v, r = self.recipe_run('food_assistance_outreach', 'house', '005')
        picks = [r['claims'][0]['claim_ref']]
        bundle = dict(Flow.bundle(v), selected_claim_refs=picks)
        for extra in ({'staff_edits': {'note': 'x'}}, {'checklist_edits': []}, {'tracking': None}):
            self.assertEqual(code_of(lambda: self.call('build_brief', dict(bundle, **extra)))[0], 'invalid_arguments')
        bogus = {'action_id': 'snap_verify/1', 'semantic_hash': 'sha256:' + '5' * 64}
        self.assertEqual(code_of(lambda: self.call('build_brief', dict(bundle, selected_action_ref=bogus)))[0], 'action_conflict')
        self.assertEqual(code_of(lambda: self.call('build_brief', dict(bundle, selected_claim_refs=[])))[0], 'invalid_arguments')
        ok = self.call('build_brief', bundle)
        self.assertEqual(ok['brief']['entries'][0]['finding_id'], r['claims'][0]['finding_id'])

    def test_brief_overflow_is_reported_not_clipped(self):
        p = self.flow.prepare(EIGHT_Q)
        v = self.flow.validate(p, eight_step_decision())
        r = self.flow.run(v)
        big = [c['claim_ref'] for c in r['claims'] if c['kind'] in ('outreach_hypothesis', 'program_relevance')][:8]
        code, exc = code_of(lambda: self.call('build_brief', dict(Flow.bundle(v), selected_claim_refs=big)))
        self.assertEqual((code, exc.retry_action), ('brief_overflow', 'shorten_brief'))


class AdmissionTests(Base):
    def test_bounded_admission_rejects_busy_without_queueing(self):
        conn = connector(max_waiting=2, wait_seconds=30)
        flow = Flow(local_call(conn))
        prepared = [flow.prepare(SENIOR_Q) for _ in range(4)]
        results, errors = [], []

        def worker(pp):
            try:
                results.append(conn.call('validate_proposal', {'request': pp['request'], 'decision': SENIOR_D, 'expected_identity': pp['identity']})[0])
            except ToolError as exc:
                errors.append(exc.code)
        conn.lock.acquire()
        try:
            threads = [threading.Thread(target=worker, args=(pp,)) for pp in prepared[:3]]
            for t in threads:
                t.start()
            time.sleep(0.3)
            code, exc = code_of(lambda: conn.call('validate_proposal', {'request': prepared[3]['request'], 'decision': SENIOR_D, 'expected_identity': self.identity}))
            self.assertEqual((code, exc.retry_action), ('busy', 'retry_in_a_few_seconds'))
        finally:
            conn.lock.release()
        for t in threads:
            t.join(30)
        self.assertEqual((len(results), errors), (3, []))
        # Lock wait timeout also yields busy, never an unbounded wait.
        slow = connector(max_waiting=2, wait_seconds=0.2)
        slow.lock.acquire()
        try:
            self.assertEqual(code_of(lambda: slow.call('prepare_question', {'utterance': SENIOR_Q}))[0], 'busy')
        finally:
            slow.lock.release()

    def test_interleaved_independent_contexts_do_not_mix(self):
        cases = [('house', '%03d' % n) for n in (2, 11, 30, 47)] + [('senate', '%03d' % n) for n in (1, 13, 25)]
        sequential = {}
        for chamber, code in cases:
            sequential[(chamber, code)] = self.recipe_run('aging_at_home', chamber, code)[2]['claims']
        conn = connector(max_waiting=len(cases), wait_seconds=60)
        flow = Flow(local_call(conn))
        out = {}

        def worker(chamber, code):
            u = f'Run the {RECIPE_LABEL["aging_at_home"]} recipe for {chamber.title()} {int(code)}.'
            out[(chamber, code)] = flow.ask_and_run(u, synthetic_decision(chamber=chamber, code=code, issue='aging_at_home', steps=recipe_steps('aging_at_home')))[2]['claims']
        threads = [threading.Thread(target=worker, args=c) for c in cases]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(out, sequential)


if __name__ == '__main__':
    unittest.main()

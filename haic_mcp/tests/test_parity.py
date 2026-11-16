"""Oracle sweep: every admitted district x both recipes through the tools vs the direct pinned engine.

The oracle is Investigation.handle on the same normalized plan (computed by the engine, not stored answers). The
synthetic decisions only name the catalog recipe for a district; the engine's guards still check them."""
from __future__ import annotations

import copy
import unittest

from haic_mcp.tests.support import RECIPE_LABEL, Flow, connector, engine, local_call, recipe_steps, synthetic_decision

DISTRICTS = [('house', '%03d' % n) for n in range(1, 52)] + [('senate', '%03d' % n) for n in range(1, 26)]


def direct(prepared, plan, mode, selected=(), action=None):
    ctx = prepared['request']['context']
    envelope = {'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1', 'recipe_version': plan['issue_id'] + '/1',
                'snapshot_id': engine().investigation.snapshot_id, 'request_id': prepared['request']['request_id'],
                'case_id': ctx['case_id'], 'branch_id': ctx['branch_id'], 'revision': ctx['revision'], 'mode': mode,
                'plan': copy.deepcopy(plan), 'selected_claim_refs': list(selected), 'selected_action_ref': action}
    if mode == 'brief':
        envelope.update(staff_edits={}, checklist_edits=[], tracking=None, edits_reviewed_for=None)
    return engine().investigation.handle(envelope)


class ParitySweep(unittest.TestCase):
    def test_all_districts_both_recipes(self):
        conn = connector()
        flow = Flow(local_call(conn))
        checked = 0
        for chamber, code in DISTRICTS:
            for issue in ('aging_at_home', 'food_assistance_outreach'):
                with self.subTest(chamber=chamber, code=code, issue=issue):
                    utterance = f'Run the {RECIPE_LABEL[issue]} recipe for {chamber.title()} {int(code)}.'
                    decision = synthetic_decision(chamber=chamber, code=code, issue=issue, steps=recipe_steps(issue))
                    prepared = flow.prepare(utterance)
                    validated = flow.validate(prepared, decision)
                    self.assertEqual(validated['status'], 'propose', validated['rejection_code'])
                    plan = validated['normalized_plan']
                    self.assertEqual((plan['district']['chamber'], plan['district']['code'], plan['issue_id']), (chamber, code, issue))
                    run = flow.run(validated)
                    oracle = direct(prepared, plan, 'run')
                    self.assertEqual(run['run_status'], oracle['status'])
                    self.assertEqual([c['claim_ref'] for c in run['claims']], [c['claim_ref'] for c in oracle['claims']])
                    self.assertEqual([c['text'] for c in run['claims']], [c['text'] for c in oracle['claims']])
                    self.assertEqual([(s['step_id'], s['status']) for s in run['steps']], [(s['step_id'], s['status']) for s in oracle['steps']])
                    self.assertEqual([r['action_ref'] for r in run['responses']], [r['action_ref'] for r in oracle['responses']])
                    caveats = {c['id']: c['text'] for c in run['caveats']}
                    self.assertEqual([caveats[i] for i in run['limitation_ids']], oracle['limitations'])
                    # Brief: first statistic plus the hypothesis (when present) and the first available action.
                    picks = [c['claim_ref'] for c in run['claims'] if c['kind'] in ('statistic', 'outreach_hypothesis')][:1]
                    picks += [c['claim_ref'] for c in run['claims'] if c['kind'] == 'outreach_hypothesis'][:1]
                    action = next((r['action_ref'] for r in run['responses'] if r['action_ref']), None)
                    brief = conn.call('build_brief', dict(Flow.bundle(validated), selected_claim_refs=picks, selected_action_ref=action))
                    oracle_brief = direct(prepared, plan, 'brief', picks, action)['brief']
                    self.assertEqual(brief[0]['brief'], {k: v for k, v in oracle_brief.items() if k != 'html'})
                    for c in oracle_brief['citations']:
                        self.assertIn(f"[{c['n']}] {c['publisher']} — {c['source_id']}.", brief[1])
                    checked += 1
        self.assertEqual(checked, 152)


if __name__ == '__main__':
    unittest.main()

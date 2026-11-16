"""The browser's answer-focused brief selection (static/case_state.js focusedBrief, run in Node, not mirrored here)
on real handler results: for every successful step of the fixture cases, the focused selection uses only that
step's listed findings, keeps the recommended agency action, and is accepted by the brief handler within the
print estimate with exactly those entries. (Case export/replay of a focused selection: tests/test_case_state.cjs.)"""
import copy
import json
import shutil
import subprocess
import unittest
import uuid
from pathlib import Path
import recommended_brief_fixture as fx
from districtbrief.core import BRIEF_PRINT_BUDGET

ROOT = Path(__file__).resolve().parents[1]
NODE = ("const C=require(process.argv[1]);const cases=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8')).cases;const out={};"
        "for(const [k,r] of Object.entries(cases)){const d=C.recommendedBrief(r);out[k]={action:d.action,steps:r.steps.map((s,j)=>{"
        "const x=C.focusedBrief(Object.assign({},r,{steps:r.steps.map((t,i)=>Object.assign({},t,{step_id:'q'+i}))}),['q'+j]);"
        "return x?{claims:x.claims.map(c=>c.claim_ref),action:x.action,requested:x.requested}:null;})};}"
        "process.stdout.write(JSON.stringify(out));")


class FocusedBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which('node')
        if node is None:raise RuntimeError('Node is required for the documented checks (node --test).')
        raw = subprocess.run([node, '-e', NODE, str(ROOT / 'static/case_state.js'), str(fx.FIXTURE)], check=True, capture_output=True, text=True).stdout
        cls.selected = json.loads(raw)
        cls.i = fx.Investigation(fx.public_app.load_core('public'))

    def test_focused_selection_uses_the_requested_step_and_fits_the_print_estimate(self):
        checked = 0
        for chamber, code, issue in fx.CASES:
            key = f'{chamber}-{code}-{issue}'
            r = fx.request(self.i, chamber, code, issue);out = self.i.handle(r)
            for j, sel in enumerate(self.selected[key]['steps']):
                step = out['steps'][j]
                with self.subTest(case=key, step=j):
                    if step['status'] != 'ok' or not step['claim_refs']:
                        self.assertIsNone(sel);continue
                    listed = {c['finding_id'] for c in step['claim_refs']}
                    ids = [c['finding_id'] for c in sel['claims']]
                    self.assertTrue(ids and set(ids) <= listed, 'only the requested step\'s findings')
                    self.assertEqual(sel['requested'], len(listed))
                    kinds = {c['finding_id']: c['kind'] for c in out['claims']}
                    if any(kinds[f] == 'comparison' for f in listed):self.assertEqual([kinds[f] for f in ids], ['comparison'])
                    else:self.assertLessEqual(len(ids), 2)
                    self.assertEqual(sel['action'], self.selected[key]['action'], 'same agency action as the recommended brief')
                    b = copy.deepcopy(r);b.update(request_id=str(uuid.uuid4()), mode='brief', selected_claim_refs=sel['claims'], selected_action_ref=sel['action'],
                                                 staff_edits={}, checklist_edits=[], tracking=None, edits_reviewed_for=None)
                    brief = self.i.handle(b)['brief']
                    self.assertLessEqual(brief['print_units'], BRIEF_PRINT_BUDGET)
                    self.assertEqual([e['finding_id'] for e in brief['entries']], ids)
                    checked += 1
        self.assertGreaterEqual(checked, 15)

    def test_population_answer_brief_differs_from_the_comparison_recommendation(self):
        # The population answer of House 028: the focused brief selects that finding (not the poverty comparison
        # the recommended brief picks).
        script = ("const C=require(process.argv[1]);const cases=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8')).cases;"
                  "const r=cases['house-028-aging_at_home'];const steps=r.steps.map((t,i)=>Object.assign({},t,{step_id:'s'+(i+1)}));"
                  "const res=Object.assign({},r,{steps});const f=C.focusedBrief(res,['s1']);const d=C.recommendedBrief(res);"
                  "process.stdout.write(JSON.stringify({focused:f.claims.map(c=>c.claim_ref.finding_id),default:d.claims.map(c=>c.claim_ref.finding_id),requested:f.requested}));")
        out = json.loads(subprocess.run([shutil.which('node'), '-e', script, str(ROOT / 'static/case_state.js'), str(fx.FIXTURE)], check=True, capture_output=True, text=True).stdout)
        self.assertEqual(out['default'], ['cmp:HI-HOUSE-028-2024~HI-STATE-2024:poverty_rate_65_plus'])
        self.assertTrue(all(f.startswith('stat:HI-HOUSE-028-2024:') for f in out['focused']))
        self.assertEqual(len(out['focused']), 2);self.assertEqual(out['requested'], 4)


if __name__ == '__main__':
    unittest.main()


class AdministrativeRowFocusTests(unittest.TestCase):
    """A question that adds one administrative row to a kept administrative step: the server's typed diff names only
    that row, the browser's focus (language_state.js requestedFocus + case_state.js focusedBrief, run in Node) selects
    exactly that row's finding, and the real brief handler prints it."""
    STATIC = ROOT / 'static'

    def test_added_administrative_row_is_the_answer_and_the_brief(self):
        from districtbrief.ia_language import typed_diff
        i = fx.Investigation(fx.public_app.load_core('public'))
        rows = ['hi_snap_sfy2027_001', 'hi_snap_sfy2027_002', 'hi_snap_sfy2027_003', 'hi_snap_sfy2027_004']
        d = {'state_fips': '15', 'chamber': 'house', 'code': '028', 'boundary_session': 2024}
        plan = lambda ids: {'district': d, 'map_session': 2026, 'issue_id': 'custom', 'service_area_id': None,
                            'steps': [{'step_id': 's1', 'operation': 'administrative_evidence', 'args': {'observation_ids': ids}}]}
        before, after = plan(rows[:3]), plan(rows)
        r = {**{k: str(uuid.uuid4()) for k in ('request_id', 'case_id', 'branch_id')}, 'revision': 1, 'schema_version': 'haic-investigation/1',
             'operation_version': 'ia-core/1', 'recipe_version': 'custom/1', 'snapshot_id': i.snapshot_id, 'mode': 'run', 'plan': after,
             'selected_claim_refs': [], 'selected_action_ref': None}
        out = i.handle(r)
        self.assertEqual([s['status'] for s in out['steps']], ['ok'])
        proposal = {'normalized_plan': after, 'typed_diff': typed_diff(before, after)}
        res = {'plan': {'district': d}, 'steps': out['steps'], 'claims': out['claims'], 'responses': out['responses']}
        script = ("const L=require(process.argv[1]),C=require(process.argv[2]);const x=JSON.parse(require('fs').readFileSync(0,'utf8'));"
                  "const f=L.requestedFocus(x.proposal,null);const b=C.focusedBrief(x.res,f.step_ids,f.only);"
                  "process.stdout.write(JSON.stringify({focus:f,lead:C.focusedFindings(x.res,f.step_ids,f.only).map(c=>c.observation_id),claims:b?b.claims.map(c=>c.claim_ref):[],action:b?b.action:null}));")
        got = json.loads(subprocess.run([shutil.which('node'), '-e', script, str(self.STATIC / 'language_state.js'), str(self.STATIC / 'case_state.js')],
                                        input=json.dumps({'proposal': proposal, 'res': res}), check=True, capture_output=True, text=True).stdout)
        self.assertEqual(got['focus'], {'step_ids': ['s1'], 'only': {'s1': {'observation_ids': ['hi_snap_sfy2027_004']}}})
        self.assertEqual(got['lead'], ['hi_snap_sfy2027_004'])
        asked = next(c for c in out['claims'] if c.get('observation_id') == 'hi_snap_sfy2027_004')
        self.assertEqual([c['finding_id'] for c in got['claims']], [asked['claim_ref']['finding_id']])
        b = copy.deepcopy(r);b.update(request_id=str(uuid.uuid4()), mode='brief', selected_claim_refs=got['claims'], selected_action_ref=got['action'],
                                     staff_edits={}, checklist_edits=[], tracking=None, edits_reviewed_for=None)
        brief = i.handle(b)['brief']
        self.assertEqual([e['finding_id'] for e in brief['entries']], [asked['claim_ref']['finding_id']])
        self.assertIn('78,143', brief['html'])
        self.assertLessEqual(brief['print_units'], BRIEF_PRINT_BUDGET)

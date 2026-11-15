"""The browser's recommended-brief selection on real results: the fixture matches current handler output, the
selection computed by static/case_state.js (run in Node, not mirrored here) is accepted by the brief handler
within the print estimate, and the agency step then prints its recorded referral contact. Manual selection of
the program reference is still accepted. Requires Node, as the documented checks do."""
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
NODE = ("const C=require(process.argv[1]);const cases=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8')).cases;"
        "const out={};for(const [k,r] of Object.entries(cases)){const rec=C.recommendedBrief(r);out[k]={claims:rec.claims.map(c=>c.claim_ref),action:rec.action};}"
        "process.stdout.write(JSON.stringify(out));")


class RecommendedBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if cls.node is None:raise RuntimeError('Node is required for the documented checks (node --test).')
        cls.built = fx.build()
        raw = subprocess.run([cls.node, '-e', NODE, str(ROOT / 'static/case_state.js'), str(fx.FIXTURE)], check=True, capture_output=True, text=True).stdout
        cls.selected = json.loads(raw)

    def test_fixture_matches_current_handler_output(self):
        self.assertEqual(json.loads(fx.FIXTURE.read_text())['cases'], self.built['cases'])

    def test_selector_output_is_accepted_and_prints_the_referral_contact(self):
        i = fx.Investigation(fx.public_app.load_core('public'))
        for chamber, code, issue in fx.CASES:
            key = f'{chamber}-{code}-{issue}'
            with self.subTest(case=key):
                r = fx.request(i, chamber, code, issue);out = i.handle(r);sel = self.selected[key]
                b = copy.deepcopy(r);b.update(request_id=str(uuid.uuid4()), mode='brief', selected_claim_refs=sel['claims'], selected_action_ref=sel['action'],
                                             staff_edits={}, checklist_edits=[], tracking=None, edits_reviewed_for=None)
                brief = i.handle(b)['brief']
                self.assertLessEqual(brief['print_units'], BRIEF_PRINT_BUDGET)
                self.assertEqual([e['finding_id'] for e in brief['entries']], [c['finding_id'] for c in sel['claims']])
                if sel['action']:
                    ref = next(c for c in out['claims'] if c['kind'] == 'program_relevance')['referral']
                    self.assertIn('Referral: ' + ref['url'], brief['html']);self.assertIn(ref['phone'], brief['html'])
                    self.assertIn('Eligibility facts the agency determines', brief['html'])
                    # Manual choice: adding the program reference tile is still accepted, and then the contact is not repeated.
                    prog = next(c for c in out['claims'] if c['kind'] == 'program_relevance')['claim_ref']
                    b2 = copy.deepcopy(b);b2.update(request_id=str(uuid.uuid4()), selected_claim_refs=sel['claims'] + [prog])
                    html = i.handle(b2)['brief']['html']
                    self.assertIn('data-finding-id="prog:', html);self.assertNotIn('· Referral: ', html)


if __name__ == '__main__':
    unittest.main()

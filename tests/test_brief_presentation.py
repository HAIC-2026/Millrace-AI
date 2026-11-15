"""Printed-brief and source-view presentation: less repetition, same facts, direct official links."""
import copy
import re
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import public_app  # noqa: E402
from districtbrief import render  # noqa: E402
from districtbrief.core import L_EDITS  # noqa: E402
from districtbrief.interpret import food_assistance_recipe, recipe  # noqa: E402
from districtbrief.investigation import Investigation  # noqa: E402

I = Investigation(public_app.load_core('public'))


def run(chamber, code, builder=recipe, version='aging_at_home/1'):
    r = {**{k: str(uuid.uuid4()) for k in ('request_id', 'case_id', 'branch_id')}, 'revision': 1,
         'schema_version': 'haic-investigation/1', 'operation_version': 'ia-core/1', 'recipe_version': version,
         'snapshot_id': I.snapshot_id, 'mode': 'run',
         'plan': builder({'state_fips': '15', 'chamber': chamber, 'code': code, 'boundary_session': 2024}),
         'selected_claim_refs': [], 'selected_action_ref': None}
    return r, I.handle(r)


def brief(r, o, kinds):
    picks = [c for k in kinds for c in o['claims'] if c['kind'] == k][:len(kinds)]
    action = next(x for x in o['responses'] if x['tier'] == 'verification_action')['action_ref']
    b = copy.deepcopy(r)
    b.update(mode='brief', selected_claim_refs=[c['claim_ref'] for c in picks], selected_action_ref=action,
             staff_edits={}, checklist_edits=[], tracking=None, edits_reviewed_for=None)
    return I.handle(b)['brief']


def visible(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


class BriefPresentationTests(unittest.TestCase):
    def test_agency_name_is_not_repeated_when_its_program_reference_is_selected(self):
        r, o = run('house', '013')
        with_ref = brief(r, o, ['comparison', 'program_relevance'])
        action = with_ref['html'][with_ref['html'].index('<h3>Agency action</h3>'):]
        self.assertTrue(action.startswith('<h3>Agency action</h3><p>Kūpuna Care · Reference checked'))
        self.assertIn('Executive Office on Aging', visible(with_ref['html']))  # still named once, by the reference
        self.assertIn('House 013 includes Kalawao', visible(with_ref['html']))
        without_ref = brief(r, o, ['comparison'])
        self.assertIn('Kūpuna Care · Hawaiʻi DOH Executive Office on Aging', visible(without_ref['html']))

    def test_staff_edit_limitation_is_carried_by_inline_labels(self):
        r, o = run('house', '028')
        b = brief(r, o, ['comparison', 'program_relevance'])
        self.assertIn(L_EDITS, b['limitations'])  # still part of the record and the conservative estimate
        self.assertNotIn(L_EDITS, b['html'])
        self.assertIn('staff work, not verified facts', b['html'])

    def test_map_context_keeps_facts_and_cites_instead_of_repeating_the_source(self):
        r, o = run('senate', '006', food_assistance_recipe, 'food_assistance_outreach/1')
        b = brief(r, o, ['statistic', 'program_relevance'])
        ctx = visible(b['html'][b['html'].index('brief-map-context'):b['html'].index('</section>', b['html'].index('brief-map-context'))])
        for fact in ('Poverty rate, all people', '90% MOE', 'display class', 'Illustrative bins:', 'not policy thresholds or statistical tests',
                     'rank, significance, eligibility or causality', 'universe: Population for whom poverty status is determined', '[1]'):
            self.assertIn(fact, ctx)
        self.assertNotIn(b['district_indicator']['source_title'], ctx)
        self.assertIn('acs2024_5yr', b['html'])  # the Sources list keeps the address

    def test_official_addresses_are_direct_links(self):
        cat = I.core.catalog()
        html = render.sources_html(cat)
        for s in cat['sources']:
            if s['url'].startswith('https://'):
                self.assertIn(f'href="{render.e(s["url"])}" target="_blank" rel="noopener noreferrer"', html)
        self.assertEqual(render._official_link('javascript:alert(1)', 'x'), 'x')
        self.assertEqual(render._official_link('http://example.org', 'x'), 'x')


if __name__ == '__main__':
    unittest.main()

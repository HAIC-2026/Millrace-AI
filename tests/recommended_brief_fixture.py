"""Builds the recommended-brief selector fixture from real handler runs (projection of the fields the browser
selector reads). Used by test_recommended_brief.py (drift check) and to regenerate
tests/fixtures/recommended-brief-results.json: python tests/recommended_brief_fixture.py --write"""
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import public_app  # noqa: E402
from districtbrief.interpret import food_assistance_recipe, recipe  # noqa: E402
from districtbrief.investigation import Investigation  # noqa: E402

FIXTURE = Path(__file__).parent / 'fixtures' / 'recommended-brief-results.json'
CASES = (('house', '013', 'aging_at_home'), ('house', '028', 'aging_at_home'), ('senate', '025', 'aging_at_home'),
         ('senate', '006', 'food_assistance_outreach'), ('house', '028', 'food_assistance_outreach'), ('house', '028', 'custom'))


def request(i, chamber, code, issue):
    d = {'state_fips': '15', 'chamber': chamber, 'code': code, 'boundary_session': 2024}
    plan = (recipe(d) if issue == 'aging_at_home' else food_assistance_recipe(d) if issue == 'food_assistance_outreach' else
            {'district': d, 'map_session': 2026, 'issue_id': 'custom', 'service_area_id': None,
             'steps': [{'step_id': 's1', 'operation': 'profile', 'args': {'metric_ids': ['median_age', 'population_65_plus', 'total_households']}}]})
    return {**{k: str(uuid.uuid4()) for k in ('request_id', 'case_id', 'branch_id')}, 'revision': 1, 'schema_version': 'haic-investigation/1',
            'operation_version': 'ia-core/1', 'recipe_version': issue + '/1', 'snapshot_id': i.snapshot_id, 'mode': 'run', 'plan': plan,
            'selected_claim_refs': [], 'selected_action_ref': None}


def project(out, plan):
    # The browser keeps the applied plan with its stored results (results.plan); the handler reply has none.
    return {'plan': {'district': plan['district']},
            'steps': [{'status': s['status'], 'claim_refs': s['claim_refs']} for s in out['steps']],
            'claims': [{'kind': c['kind'], 'claim_ref': c['claim_ref'],
                        **({'metric': {'metric_id': c['metric']['metric_id']}} if isinstance(c.get('metric'), dict) else {}),
                        **({'geography': {'geography_id': c['geography']['geography_id']}} if isinstance(c.get('geography'), dict) else {}),
                        **({'program': {'program_id': c['program']['program_id']}} if isinstance(c.get('program'), dict) else {})}
                       for c in out['claims']],
            'responses': [{'tier': r['tier'], 'program_id': r['program_id'], 'action_ref': r['action_ref']} for r in out['responses']]}


def build():
    i = Investigation(public_app.load_core('public'))
    cases = {}
    for c, n, issue in CASES:
        r = request(i, c, n, issue)
        cases[f'{c}-{n}-{issue}'] = project(i.handle(r), r['plan'])
    return {'note': 'Generated from real handler runs; projection only. Regenerate with --write.', 'cases': cases}


if __name__ == '__main__' and '--write' in sys.argv:
    FIXTURE.write_text(json.dumps(build(), indent=1, sort_keys=True) + '\n')

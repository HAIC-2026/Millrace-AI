import copy
import unittest
import uuid
from unittest.mock import patch
from public_app import load_core,ROOT
from districtbrief.core import Core
from districtbrief.case_contract import InvestigationError, OPERATION_VERSION, SCHEMA_VERSION
from districtbrief.claim_binding import ClaimBindings,canonical_bytes,digest
from districtbrief.interpret import recipe
from districtbrief.investigation import Investigation

class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.core=load_core();cls.snapshot=cls.core.metadata.combined_snapshot_id(cls.core.snapshot_id)
    def bind(self,f):return ClaimBindings(self.core,self.snapshot).bind(f)
    def test_equal_number_cannot_substitute_semantics(self):
        f=self.core.stat_finding('HI-HOUSE-028-2024:poverty_rate_65_plus');original=self.bind(f)['claim_ref']
        paths=[('metric','metric_id'),('metric','variable_id'),('universe',),('geography','chamber'),('geography','boundary_session'),('period','start_year'),('source','locator'),('annotation',)]
        for path in paths:
            g=copy.deepcopy(f);target=g
            for key in path[:-1]:target=target[key]
            key=path[-1];target[key]=({'sheet':'DP03','estimate_cell':'A1','moe_cell':'A2'} if key=='locator' else 'substituted')
            # Invalid geographic identity is rejected rather than rebound by a coincidentally equal number.
            try:changed=self.bind(g)['claim_ref']
            except (KeyError,ValueError,TypeError):continue
            self.assertNotEqual(original,changed,path)
    def test_ordered_operands_and_nfc(self):
        a={'operands':[{'finding_id':'left'},{'finding_id':'right'}]};b={'operands':list(reversed(a['operands']))}
        self.assertNotEqual(digest(a),digest(b));self.assertEqual(canonical_bytes({'s':'Hawai\u02bbi'}),canonical_bytes({'s':'Hawai\u02bbi'}))
        self.assertEqual(digest({'s':'Ku\u0304puna'}),digest({'s':'Kūpuna'}))
    def test_program_and_hypothesis_bind_full_subject_and_map_compatibility(self):
        for f in [self.core.prog_finding('kupuna_care_hi','HI-HOUSE-013-2024'),self.core.lead_finding('kupuna_care_hi','HI-HOUSE-013-2024')]:
            a=ClaimBindings(self.core,self.snapshot,2024).bind(f);b=ClaimBindings(self.core,self.snapshot,2026).bind(f)
            g=b['binding']['geography']
            for key in ('type','state_fips','chamber','code','boundary_session','geoid','summary_level','boundary_vintage','compatibility'):
                self.assertIn(key,g)
            self.assertEqual(g['chamber'],'house');self.assertEqual(g['code'],'013');self.assertEqual(g['compatibility']['map_session'],2026)
            self.assertNotEqual(a['claim_ref']['semantic_hash'],b['claim_ref']['semantic_hash'])

    def test_source_hash_and_snapshot_bind(self):
        f=self.core.stat_finding('HI-HOUSE-013-2024:population_65_plus');b=self.bind(f)['binding'];changed=copy.deepcopy(b);changed['source_records'][0]['retained_hash']='0'*64
        self.assertNotEqual(digest(b),digest(changed));changed=copy.deepcopy(b);changed['snapshot_id']='sha256:'+'0'*64;self.assertNotEqual(digest(b),digest(changed))

    def run_request(self, map_session):
        plan = recipe({'state_fips': '15', 'chamber': 'house', 'code': '028', 'boundary_session': 2024})
        plan['map_session'] = map_session
        return {
            **{key: str(uuid.uuid4()) for key in ('request_id', 'case_id', 'branch_id')},
            'revision': 1, 'schema_version': SCHEMA_VERSION, 'operation_version': OPERATION_VERSION,
            'recipe_version': 'aging_at_home/1', 'snapshot_id': self.snapshot, 'mode': 'run',
            'plan': plan, 'selected_claim_refs': [], 'selected_action_ref': None,
        }

    def test_map_reselection_reconstructs_exact_live_statistic_bindings_both_ways(self):
        investigation = Investigation(self.core)
        before = self.run_request(2024)
        after = copy.deepcopy(before)
        after.update(request_id=str(uuid.uuid4()), branch_id=str(uuid.uuid4()))
        after['plan']['map_session'] = 2026
        results = {session: investigation.handle(request) for session, request in ((2024, before), (2026, after))}
        self.assertIs(self.core.geo.geometry_equal_across_sessions('house', '028'), True)
        for previous, current, request in ((2024, 2026, after), (2026, 2024, before)):
            with self.subTest(previous=previous, current=current):
                result = results[current]
                proof = result['map_reselection']
                self.assertEqual((proof['from_map_session'], proof['to_map_session']), (previous, current))
                self.assertEqual([pair['current_ref'] for pair in proof['refs']], result['steps'][0]['claim_refs'])
                self.assertEqual([pair['previous_ref'] for pair in proof['refs']], results[previous]['steps'][0]['claim_refs'])
                self.assertGreater(len(result['claims']), len(proof['refs']))
                for pair in proof['refs']:
                    old_ref, new_ref = pair['previous_ref'], pair['current_ref']
                    finding = self.core.finding(new_ref['finding_id'])
                    old_claim = ClaimBindings(self.core, self.snapshot, previous).bind(finding)
                    new_claim = ClaimBindings(self.core, self.snapshot, current).bind(finding)
                    self.assertEqual(old_ref, old_claim['claim_ref'])
                    self.assertEqual(new_ref, new_claim['claim_ref'])
                    self.assertNotEqual(old_ref['semantic_hash'], new_ref['semantic_hash'])
                    self.assertNotEqual(canonical_bytes(old_claim['binding']), canonical_bytes(new_claim['binding']))
                    reconstructed = copy.deepcopy(new_claim['binding'])
                    reconstructed['geography']['compatibility']['map_session'] = previous
                    self.assertEqual(canonical_bytes(reconstructed), canonical_bytes(old_claim['binding']))
                    self.assertEqual(next(c['claim_ref'] for c in result['claims']
                                          if c['finding_id'] == new_ref['finding_id']), new_ref)
                old_ref, new_ref = proof['refs'][0]['previous_ref'], proof['refs'][0]['current_ref']
                run_with_old = dict(request, selected_claim_refs=[old_ref])
                self.assertEqual(investigation.handle(run_with_old)['selection_review'][0]['state'], 'retired')
                brief_request = dict(run_with_old, mode='brief', staff_edits={}, checklist_edits=[],
                                     tracking=None, edits_reviewed_for=None)
                with self.assertRaises(InvestigationError) as error:
                    investigation.handle(brief_request)
                self.assertEqual((error.exception.status, error.exception.code), (409, 'selection_conflict'))
                brief_result = investigation.handle(dict(brief_request, selected_claim_refs=[new_ref]))
                self.assertNotIn('map_reselection', brief_result)
                brief = brief_result['brief']
                self.assertEqual((brief['map_session'], brief['statistical_session']), (current, 2024))
                self.assertEqual([entry['finding_id'] for entry in brief['entries']], [new_ref['finding_id']])
                self.assertEqual(brief['entries'][0]['text'], self.core.finding(new_ref['finding_id'])['text'])

    def test_map_reselection_requires_equal_geometry_and_successful_direct_profile(self):
        investigation = Investigation(self.core)
        geo = copy.copy(self.core.geo)
        geo._cross = dict(geo._cross)
        geo._records = dict(geo._records)
        shapes = {}
        for session, width in ((2024, 1), (2026, 2)):
            key = ('house', session, '028')
            geo._records[key] = geo.get('house', '028', session)
            shapes[key] = {'type': 'Polygon', 'coordinates': [[[0, 0], [width, 0], [width, 1], [0, 1], [0, 0]]]}
        geo._link_sessions(shapes)
        self.assertIs(geo.geometry_equal_across_sessions('house', '028'), False)
        for session in (2024, 2026):
            request = self.run_request(session)
            with patch.object(self.core, 'geo', geo):
                result = investigation.handle(request)
                self.assertEqual(result['status'], 'ok')
                self.assertTrue(result['steps'][0]['claim_refs'])
                self.assertNotIn('map_reselection', result)
            with patch.object(self.core, 'profile', side_effect=RuntimeError('fixture profile failure')):
                result = investigation.handle(request)
                self.assertEqual(result['status'], 'partial')
                self.assertTrue(any(claim['kind'] == 'statistic' for claim in result['claims']))
                self.assertNotIn('map_reselection', result)
            request['plan']['steps'] = request['plan']['steps'][1:]
            result = investigation.handle(request)
            self.assertEqual(result['status'], 'ok')
            self.assertTrue(any(claim['kind'] == 'statistic' for claim in result['claims']))
            self.assertNotIn('map_reselection', result)

    def test_map_reselection_keeps_proof_when_an_independent_step_fails(self):
        investigation = Investigation(self.core)
        request = self.run_request(2026)
        request['plan']['steps'][1]['args']['comparison_geography'] = 'HI-COUNTY-999-2024'
        result = investigation.handle(request)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([pair['current_ref'] for pair in result['map_reselection']['refs']],
                         result['steps'][0]['claim_refs'])

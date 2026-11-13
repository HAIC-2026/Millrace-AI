import json
import shutil
import tempfile
import unittest
from pathlib import Path
from districtbrief.public_packet import public_metadata as CandidateMetadata
from districtbrief.service_scope import ServiceScope

ROOT = Path(__file__).resolve().parents[1]
class ScopeTests(unittest.TestCase):
    def test_scope_never_derives_program_coverage_from_district_or_selection(self):
        scope = ServiceScope(CandidateMetadata(ROOT / 'candidate-metadata'))
        for code in ('013','028'):
            district = {'state_fips':'15','chamber':'house','code':code,'boundary_session':2024}
            for program in ('kupuna_care_hi','hcv_honolulu'):
                value = scope.resolve(district, program, 'kalawao')
                self.assertEqual(value['jurisdiction']['state'], 'unknown')
                self.assertEqual(value['eligibility_area'], 'unknown')
                self.assertEqual(value['access']['state'], 'unknown')
        self.assertIn('Kalawao', ' '.join(scope.resolve(district | {'code':'013'}, 'kupuna_care_hi')['access']['questions']))

    def test_program_questions_and_referrals_stay_with_their_agency(self):
        from districtbrief.core import Core
        from public_app import load_core
        core = load_core()
        district = {'state_fips':'15', 'chamber':'house', 'code':'013', 'boundary_session':2024}
        scope = core.service_scope
        kupuna = scope.resolve(district, 'kupuna_care_hi', 'kalawao')
        self.assertIn('808-586-0100', ' '.join(kupuna['access']['questions']))
        for program in ('snap_hi', 'medquest_hi', 'hcv_honolulu', 'wic_hi'):
            questions = ' '.join(scope.resolve(district, program, 'kalawao')['access']['questions']).casefold()
            for unrelated in ('aging', '808-586-0100', 'executive office on aging'):
                self.assertNotIn(unrelated, questions, program)
            finding = core.prog_finding(program, 'HI-HOUSE-013-2024')
            self.assertNotIn('808-586-0100', ' '.join(finding['scope_questions']))
        snap = core.prog_finding('snap_hi', 'HI-HOUSE-013-2024')
        self.assertIn('BESSD', snap['referral']['next_step'])
        self.assertEqual(snap['referral']['phone'], '1-855-643-1643')
        self.assertEqual(snap['referral']['url'], 'https://pais.dhs.hawaii.gov/PAIS/#!/')

    def test_metadata_tampering_and_extra_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'metadata'
            shutil.copytree(ROOT / 'candidate-metadata', root)
            CandidateMetadata(root)
            (root / 'recipes/aging_at_home.v1.json').write_text('{}')
            with self.assertRaises(ValueError): CandidateMetadata(root)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'metadata'
            shutil.copytree(ROOT / 'candidate-metadata', root)
            (root / 'extra').write_text('x')
            with self.assertRaises(ValueError): CandidateMetadata(root)

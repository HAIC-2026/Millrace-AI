"""Publication projection integrity and cross-profile refusal checks."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch
from public_app import Application, ROOT, RuntimePacket, load_core
from districtbrief.case_contract import InvestigationError
from districtbrief.claim_binding import ClaimBindings
from districtbrief.interpret import recipe
from districtbrief.packet import PacketError
from districtbrief.public_packet import PublicPacket

R2_SNAPSHOT = 'sha256:143fb7cbdf10a8a3b05a30228e44c347a2cd21d93819a3a3e79094dc847887d3'


class PublicProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = load_core('public')

    def test_origin_verification_is_honest(self):
        self.assertFalse(self.core.packet.verification['full_r2_archive_verified'])
        sources = self.core.packet.sources
        retained = {sid for sid in sources if self.core.packet.source_file_status(sid)['available']}
        self.assertEqual(retained, {'tigerweb_2024_house_geometry','tigerweb_2024_senate_geometry',
                                   'tigerweb_2026_house_geometry','tigerweb_2026_senate_geometry'})
        ref = ClaimBindings(self.core, self.core.metadata.combined_snapshot_id(self.core.snapshot_id)).bind(
            self.core.stat_finding('HI-HOUSE-028-2024:population_65_plus'))
        self.assertFalse(ref['binding']['source_records'][0]['origin_bytes_verified'])
        self.assertEqual(ref['binding']['source_records'][0]['verification_scope'],
                         'normalized_projection_with_historical_source_reference')
        detail = self.core.source('dbedt_2024_house', ref['finding_id'])['detail']
        self.assertEqual(detail['verification_kind'], 'normalized_projection')
        self.assertFalse(detail['cell_verified'])

    def test_default_rejects_old_snapshot_before_dispatch(self):
        with tempfile.TemporaryDirectory() as state_dir:
            app = Application(state_dir, secure_cookie=False, input_profile='public')
            request = {**{k:str(uuid.uuid4()) for k in ('request_id','case_id','branch_id')},
                       'revision':1,'schema_version':'haic-investigation/1','operation_version':'ia-core/1',
                       'recipe_version':'aging_at_home/1','snapshot_id':R2_SNAPSHOT,'mode':'run',
                       'plan':recipe({'state_fips':'15','chamber':'house','code':'028','boundary_session':2024}),
                       'selected_claim_refs':[],'selected_action_ref':None}
            try:
                with patch.object(app.investigation.core,'profile', side_effect=AssertionError('analytical dispatch')):
                    with self.assertRaises(InvestigationError) as error:
                        app.investigation.handle(request)
                self.assertEqual((error.exception.status,error.exception.code),(409,'snapshot_unavailable'))
                self.assertIn('r2 profile', error.exception.message)
            finally:
                for handler in app.service.metrics.handlers: handler.close()

    def test_projection_cannot_pass_legacy_verifier(self):
        with self.assertRaises(PacketError): RuntimePacket(ROOT / 'runtime-packet')
        with self.assertRaises(ValueError): load_core('r2')
        with self.assertRaises(ValueError): load_core('guessed-profile')

    def test_missing_symlink_and_edited_public_inputs_fail(self):
        for operation in ('missing','symlink','changed','extra'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'packet'
                shutil.copytree(ROOT/'runtime-packet',root)
                target = root/'data/participation/observations.json'
                if operation == 'missing': target.unlink()
                elif operation == 'symlink':
                    target.unlink(); target.symlink_to(ROOT/'runtime-packet/data/participation/observations.json')
                elif operation == 'changed': target.write_bytes(target.read_bytes()+b' ')
                else: (root/'unexpected.json').write_text('{}')
                with self.assertRaises(PacketError): PublicPacket(root)

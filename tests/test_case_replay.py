"""Exact-snapshot replay rejects unavailable evidence before analytical dispatch."""
import copy
import tempfile
import unittest
import uuid
from unittest.mock import patch
from public_app import Application
from districtbrief.interpret import recipe
from districtbrief.case_contract import InvestigationError

class ReplayTests(unittest.TestCase):
    def test_exact_replay_and_stale_block_before_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory,secure_cookie=False);i=app.investigation
            r={**{k:str(uuid.uuid4()) for k in ('request_id','case_id','branch_id')},'revision':1,'schema_version':'haic-investigation/1','operation_version':'ia-core/1','recipe_version':'aging_at_home/1','snapshot_id':i.snapshot_id,'mode':'run','plan':recipe({'state_fips':'15','chamber':'house','code':'013','boundary_session':2024}),'selected_claim_refs':[],'selected_action_ref':None}
            try:
                a=i.handle(r);b=i.handle(copy.deepcopy(r));self.assertEqual(a['claims'],b['claims'])
                for field,value in [('snapshot_id','sha256:'+'0'*64),('operation_version','ia-core/2'),('recipe_version','aging_at_home/2')]:
                    changed=copy.deepcopy(r);changed[field]=value
                    with patch.object(i.core,'profile',side_effect=AssertionError('dispatch')):
                        with self.assertRaises(InvestigationError) as exc:i.handle(changed)
                    self.assertEqual(exc.exception.status,409)
            finally:
                for handler in app.service.metrics.handlers:handler.close()

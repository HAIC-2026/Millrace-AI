import copy
import unittest
from public_app import load_core,ROOT
from districtbrief.core import Core
from districtbrief.claim_binding import ClaimBindings,canonical_bytes,digest

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

import json
import unittest
from pathlib import Path
from districtbrief.geography import GeographyIndex, geometry_payload, _validate_geometry
from public_app import load_core

ROOT=Path(__file__).resolve().parents[1]
class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet=load_core().packet
        cls.snapshot='sha256:'+'1'*64
    def test_all_features_link_and_fit_wrapper(self):
        sizes=[]
        for session in (2024,2026):
            for chamber, count in (('house',51),('senate',25)):
                for n in range(1,count+1):
                    data=geometry_payload(self.packet,self.snapshot,chamber,f'{n:03}',session)
                    self.assertEqual(data['feature']['properties']['GEOID'],'15'+f'{n:03}')
                    sizes.append(len(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()))
        self.assertLessEqual(max(sizes),1048576)
        print('geometry wrapper maximum bytes:',max(sizes))
    def test_required_components_and_finite(self):
        for chamber,code,count in [('house','009',1),('house','028',1),('house','013',3),('senate','025',10)]:
            self.assertEqual(geometry_payload(self.packet,self.snapshot,chamber,code,2026)['component_count'],count)
        with self.assertRaises(ValueError):
            _validate_geometry({'type':'Polygon','coordinates':[[[0,0],[1,0],[float('nan'),1],[0,0]]]})

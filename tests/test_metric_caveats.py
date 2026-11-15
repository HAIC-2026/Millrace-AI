"""Metric-specific caveats: each statistic carries only the limitations that describe its own population."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import public_app  # noqa: E402
from districtbrief.core import POVERTY_UNIVERSE_NOTE  # noqa: E402

CORE = public_app.load_core('public')
AGE_SENTENCE = 'Age-specific poverty rate'


class MetricCaveatTests(unittest.TestCase):
    def ids(self, metric):
        return [o for o in CORE.observations if o.endswith(':' + metric)]

    def test_all_people_poverty_has_universe_note_without_senior_caveat(self):
        ids = self.ids('poverty_rate_all_people')
        self.assertEqual(len(ids), 82)
        for oid in ids:
            lims = CORE.stat_finding(oid)['limitations']
            self.assertIn(POVERTY_UNIVERSE_NOTE, lims, oid)
            self.assertFalse(any(AGE_SENTENCE in l or 'seniors' in l for l in lims), oid)

    def test_senior_poverty_keeps_full_age_specific_caveat(self):
        for oid in self.ids('poverty_rate_65_plus'):
            lims = CORE.stat_finding(oid)['limitations']
            self.assertIn(CORE.stat_limitations[1], lims, oid)
            self.assertTrue(CORE.stat_limitations[1].startswith(POVERTY_UNIVERSE_NOTE + ' '))

    def test_comparison_inherits_metric_specific_caveat_and_values_unchanged(self):
        f = CORE.cmp_finding('HI-SENATE-006-2024', 'HI-STATE-2024', 'poverty_rate_all_people')
        self.assertFalse(any(AGE_SENTENCE in l for l in f['limitations']))
        s = CORE.stat_finding('HI-SENATE-006-2024:poverty_rate_all_people')
        o = CORE.observations['HI-SENATE-006-2024:poverty_rate_all_people']
        self.assertEqual((s['estimate'], s['margin_of_error'], s['unit'], s['universe']),
                         (o['estimate'], o['margin_of_error'], o['unit'], o['universe']))

    def test_social_security_caveat_only_on_household_receipt_measure(self):
        note = CORE.stat_limitations[2]
        for oid in CORE.observations:
            has = note in CORE.stat_finding(oid)['limitations']
            self.assertEqual(has, oid.endswith(':households_with_social_security'), oid)


if __name__ == '__main__':
    unittest.main()

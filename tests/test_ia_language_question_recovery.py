"""Proven unsupported requests stay unsupported when the model asks a clarifying question.

Offline strict-function decisions only; the job test injects provider transport and a temporary ledger.
"""
import unittest

import test_ia_language_repair as repair
from districtbrief.interpret import recipe
from test_ia_language_repair import decision, plan, wire


def metric_clarification():
    return decision('clarify', 'none', clarify_field='metric',
                    clarify_choices=['m_population_65_plus', 'm_total_population'], reason_code='missing_context')


class UnsupportedQuestionRecoveryTests(unittest.TestCase):
    setUpClass = classmethod(repair.LanguageRepairTests.setUpClass.__func__)
    request = repair.LanguageRepairTests.request
    convert = repair.LanguageRepairTests.convert

    def test_existing_unsupported_operations_recover_on_both_paths(self):
        for text in ('Forecast senior population in House 28.',
                     'How many residents in House 28 are eligible for SNAP?',
                     'Show unmet need for SNAP in House 28.',
                     'What causes senior poverty in House 28?',
                     'Show live availability of SNAP in House 28.',
                     'Give me population forecasts for House 28.',
                     'Show forecasted senior population in House 28.',
                     'Population predictions for House 28.'):
            for d in (metric_clarification(), decision(p=wire(plan()))):
                with self.subTest(text=text, model_status=d['status']):
                    out = self.convert(text, d)
                    self.assertEqual((out['status'], out['reason_code'], out.get('recovered_from')),
                                     ('unsupported', 'unsupported_operation', 'unsupported_explicit_constraint'))
                    self.assertEqual((out['normalized_plan'], out['choices'], out['typed_diff']), (None, [], []))

    def test_negated_and_unproven_constraints_keep_model_clarification(self):
        for text in ("Don't forecast; show population in House 28.",
                     "Don\u2019t forecast; show population in House 28.",
                     "Please don\u2019t determine eligibility; show population in House 28.",
                     'No forecasts; show population in House 28.',
                     'No unmet need estimate; show population in House 28.',
                     'Without causal analysis, show population in House 28.',
                     'Show population in House 28; do not determine eligibility.',
                     'SNAP eligibility reference for House 28.',
                     'Compare senior population in House 28 with the State.'):
            with self.subTest(text=text):
                out = self.convert(text, metric_clarification())
                self.assertEqual((out['status'], out['clarify_field']), ('clarify', 'metric'))
                self.assertNotIn('recovered_from', out)

    def test_source_referent_clarification_is_not_an_operation_request(self):
        # Source inspection asks about a figure; like the inspect_source proposal, its referent clarification stays.
        referent = decision('clarify', 'none', clarify_field='referent', clarify_choices=['r_selected_1', 'r_selected_2'],
                            reason_code='ambiguous_reference')
        for text in ('Is that figure a forecast?', 'Are those figures forecasts?', 'Does that figure count who is eligible?'):
            with self.subTest(text=text):
                out = self.convert(text, referent, recipe(repair.H('028')), selections=2)
                self.assertEqual((out['status'], out['clarify_field']), ('clarify', 'referent'))
                self.assertNotIn('recovered_from', out)
        out = self.convert('Is that figure statistically significant?', referent, recipe(repair.H('028')), selections=2)
        self.assertEqual((out['status'], out['reason_code'], out.get('recovered_from')),
                         ('unsupported', 'unsupported_operation', 'unsupported_explicit_constraint'))


class UnsupportedQuestionJobTests(unittest.TestCase):
    setUpClass = classmethod(repair.LanguageRepairJobTests.setUpClass.__func__)
    setUp = repair.LanguageRepairJobTests.setUp
    tearDown = repair.LanguageRepairJobTests.tearDown
    body = repair.LanguageRepairJobTests.body
    run_job = repair.LanguageRepairJobTests.run_job

    def test_clarification_recovery_is_attributed_and_settled(self):
        out, events = self.run_job('Forecast senior population in House 28.', metric_clarification())
        self.assertEqual((out['status'], out['reason_code'], out['normalized_plan'], out['choices']),
                         ('unsupported', 'unsupported_operation', None, []))
        self.assertEqual(out['attribution'], {'decision_origin': 'server_recovery', 'model_status': 'clarify',
                                             'model_intent': 'none', 'recovery_category': 'unsupported_inference',
                                             'failure_class': 'none'})
        self.assertNotIn('recovered_from', out)
        self.assertEqual(events['local_result']['recovered_from'], 'unsupported_explicit_constraint')
        self.assertEqual(events['provider_result']['settlement'], 'known_usage_settled')


if __name__ == '__main__':
    unittest.main()

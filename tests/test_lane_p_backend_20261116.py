"""Tests for comparator-positioned bare numbers in a model district clarification, statistical
significance in a model clarification, and the literal 'add <program> for <district>' bootstrap. Offline, scripted
provider decisions through the production prepare/convert path; zero model calls."""
import re
import unittest
from districtbrief.interpret import interpret, recipe
import test_ia_language_repair as repair
from test_ia_language_repair import H, decision, plan, compare, profile, wire

def clarify(field, *choices):
    return decision('clarify', 'none', clarify_field=field, clarify_choices=list(choices), reason_code='missing_context')

class ComparatorClarificationTests(unittest.TestCase):
    setUpClass = classmethod(repair.LanguageRepairTests.setUpClass.__func__)
    request = repair.LanguageRepairTests.request; convert = repair.LanguageRepairTests.convert
    def held(self): return recipe(H('028'))
    def comparator(self, text, d, confirmed, expected):
        out = self.convert(text, d, confirmed)
        self.assertEqual((out['status'], out['clarify_field'], out.get('recovered_from')),
                         ('clarify', 'comparator', 'explicit_comparator_chamber_missing'), text)
        self.assertEqual([c['value'] for c in out['choices']], expected, text)
        self.assertIsNone(out['normalized_plan'])

    def test_comparator_number_never_offers_primary_district_choices(self):
        both = lambda n: [f'HI-HOUSE-{n:03}-2024', f'HI-SENATE-{n:03}-2024']
        for text, d, confirmed, expected in (
                ('Compare senior poverty against district 10.', clarify('district', 'd_h010', 'd_s010'), self.held(), both(10)),
                ('Compare senior poverty against district 10.', clarify('district', 'd_s010'), self.held(), both(10)),
                ('How does median age here look versus district 7?', clarify('district', 'd_h007', 'd_s007'), self.held(), both(7)),
                ('Show senior poverty in House 28 relative to district 12.', clarify('district', 'd_h012', 'd_s012'), None, both(12)),
                ('Compare median age with district 30.', clarify('district', 'd_h030'), self.held(), ['HI-HOUSE-030-2024'])):
            with self.subTest(text=text):
                self.comparator(text, d, confirmed, expected)

    def test_primary_bare_number_and_other_clarifications_unchanged(self):
        for text in ('Use district 10.', 'Profile district 10.'):
            out = self.convert(text, clarify('district', 'd_h010', 'd_s010'), self.held())
            self.assertEqual((out['status'], out['clarify_field'], [c['alias'] for c in out['choices']]), ('clarify', 'district', ['d_h010', 'd_s010']))
        # A comparator number does not affect a clarification that offers none of its district aliases.
        out = self.convert('Compare senior poverty against district 10.', clarify('metric', 'm_poverty_rate_65_plus', 'm_poverty_rate_all_people'), self.held())
        self.assertEqual((out['status'], out['clarify_field']), ('clarify', 'metric'))

class SignificanceClarificationTests(unittest.TestCase):
    setUpClass = classmethod(repair.LanguageRepairTests.setUpClass.__func__)
    request = repair.LanguageRepairTests.request; convert = repair.LanguageRepairTests.convert

    def test_significance_clarification_becomes_existing_unsupported_recovery(self):
        metric = clarify('metric', 'm_poverty_rate_65_plus', 'm_poverty_rate_all_people')
        for text in ('Is poverty in House 28 significantly higher than the State?',
                     'Run a significance test on House 28 versus Maui County.',
                     'Is the gap between House 28 and the State statistically significant?',
                     'What is the p-value for House 28 against the State?'):
            with self.subTest(text=text):
                out = self.convert(text, metric, recipe(H('028')))
                self.assertEqual((out['status'], out['reason_code'], out['choices'], out['normalized_plan'], out.get('recovered_from')),
                                 ('unsupported', 'unsupported_operation', [], None, 'unsupported_explicit_constraint'))
        district = clarify('district', 'd_h010', 'd_s010')
        out = self.convert('Is district 10 significantly different from the State?', district, None)
        self.assertEqual(out['status'], 'unsupported')

    def test_non_statistical_or_negated_significance_keeps_clarification(self):
        for text, d in (('What is the significance of SNAP for this district?', clarify('program', 'p_snap_hi', 'p_medquest_hi')),
                        ('No significance testing needed; which poverty measure fits House 28?',
                         clarify('metric', 'm_poverty_rate_65_plus', 'm_poverty_rate_all_people'))):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text, d, recipe(H('028')))['status'], 'clarify')

class Revision2ComparatorRoleTests(unittest.TestCase):
    """Comparative and peer wording keeps a named district a comparator on all three paths."""
    setUpClass = classmethod(repair.LanguageRepairTests.setUpClass.__func__)
    request = repair.LanguageRepairTests.request; convert = repair.LanguageRepairTests.convert
    def held(self): return plan(H('005'), [profile(['median_age'])])
    def outcome(self, text, d, confirmed='held'):
        out = self.convert(text, d, self.held() if confirmed == 'held' else confirmed)
        return (out['status'], out['clarify_field'], [c['value'] for c in out['choices']])
    def test_comparative_and_peer_bare_numbers_clarify_comparator_on_all_paths(self):
        both = lambda n: [f'HI-HOUSE-{n:03}-2024', f'HI-SENATE-{n:03}-2024']
        for text, n in (('Are older adults poorer here than in district 14?', 14),
                        ('Is median age lower than for district 3?', 3),
                        ('Is the rent burden heavier than at district 22?', 22),
                        ('How does median age stack up compared with that of district 6?', 6),
                        ('Median age compared to those of district 19, please.', 19),
                        ('Compare median age with the State and district 8.', 8),
                        ('Compare median age against Kauai County or district 15.', 15),
                        ('Compare median age with House 12 plus district 4.', 4),
                        ('Is senior poverty worse than in district 40?', 40)):
            expected = both(n) if n <= 25 else [f'HI-HOUSE-{n:03}-2024']  # no nonexistent Senate 26-51
            with self.subTest(path='clarify', text=text):
                self.assertEqual(self.outcome(text, clarify('district', f'd_h{n:03}', *([f'd_s{n:03}'] if n <= 25 else []))),
                                 ('clarify', 'comparator', expected))
            # Proposal keeping the held primary with a guessed House comparator: district_provenance no longer reads the
            # comparator number as the primary; the comparator gets the typed chamber choice.
            with self.subTest(path='proposal', text=text):
                steps = [profile(['median_age'])] + [compare('median_age', g, f's{i+2}') for i, g in enumerate(
                    [x for x in ('HI-STATE-2024' if 'state' in text.lower() else None, 'HI-COUNTY-007-2024' if 'kauai' in text.lower() else None,
                                 'HI-HOUSE-012-2024' if 'house 12' in text.lower() else None) if x] + [f'HI-HOUSE-{n:03}-2024'])]
                self.assertEqual(self.outcome(text, decision(p=wire(plan(H('005'), steps)))), ('clarify', 'comparator', expected))
    def test_explicit_chamber_comparator_offered_as_district_becomes_comparator_choice(self):
        self.assertEqual(self.outcome('Compare median age against Senate 10.', clarify('district', 'd_s010')),
                         ('clarify', 'comparator', ['HI-SENATE-010-2024']))
        self.assertEqual(self.outcome('Compare median age with the State and House 30.', clarify('district', 'd_h030')),
                         ('clarify', 'comparator', ['HI-HOUSE-030-2024']))
    def test_ordinary_primary_changes_and_negated_comparators_keep_district_clarification(self):
        for text, offered in (('Switch to district 10.', ('d_h010', 'd_s010')),
                              ('Open district 10 and compare it with the State.', ('d_h010', 'd_s010')),
                              ('Compare district 9 with the State on median age.', ('d_h009', 'd_s009')),
                              ('How does district 10 compare to House 5?', ('d_h010', 'd_s010')),
                              ('Go to district 11, then compare it with the State and Maui County.', ('d_h011', 'd_s011')),
                              ('Not against district 10; just profile district 12.', ('d_h012', 'd_s012')),
                              ('Profile Senate 10 and compare it with the State.', ('d_s010',)),
                              ('Compare Senate 10 with the State and district 4.', ('d_s010',))):
            with self.subTest(text=text):
                self.assertEqual(self.outcome(text, clarify('district', *offered)), ('clarify', 'district', [
                    {'chamber': a[2] == 'h' and 'house' or 'senate', 'code': a[3:]} for a in offered]))
        # Ordinary explicit primary proposals are unaffected.
        out = self.convert('Profile median age in House 20 and compare it with the State.',
                           decision(p=wire(plan(H('020'), [profile(['median_age']), compare('median_age', 'HI-STATE-2024', 's2')]))), None)
        self.assertEqual(out['status'], 'propose')

class Revision2SignificanceTests(unittest.TestCase):
    """Common statistical-significance wording is unsupported on clarifications and proposals alike."""
    setUpClass = classmethod(repair.LanguageRepairTests.setUpClass.__func__)
    request = repair.LanguageRepairTests.request; convert = repair.LanguageRepairTests.convert
    def proposal(self): return decision(p=wire(plan(H('005'), [compare('poverty_rate_65_plus', 'HI-STATE-2024')])))
    def metric(self): return clarify('metric', 'm_poverty_rate_65_plus', 'm_poverty_rate_all_people')
    def test_common_significance_forms_are_unsupported_on_both_paths(self):
        for text in ('Is the House 5 difference from the State on senior poverty significant?',
                     'Is this gap in senior poverty for House 5 versus the State significant?',
                     'Is House 5 statistically higher than the State on senior poverty?',
                     'Is House 5 senior poverty significant at the 95% level against the State?',
                     'Run a t-test of House 5 senior poverty versus the State.',
                     'Is House 5 senior poverty significantly above the State?'):
            for label, d in (('clarify', self.metric()), ('propose', self.proposal())):
                with self.subTest(text=text, path=label):
                    out = self.convert(text, d, None)
                    self.assertEqual((out['status'], out['reason_code'], out['normalized_plan'], out.get('recovered_from')),
                                     ('unsupported', 'unsupported_operation', None, 'unsupported_explicit_constraint'))
    def test_non_statistical_and_negated_forms_unchanged_straight_and_curly(self):
        for text in ('Compare senior poverty in House 5 with the State.',
                     'A significant number of kupuna live in House 5; compare senior poverty with the State.',
                     'What is the significance of SNAP? Compare senior poverty in House 5 with the State.',
                     "I don't need a significance test; compare senior poverty in House 5 with the State.",
                     'I don\u2019t need a significance test; compare senior poverty in House 5 with the State.',
                     "Don't run a t-test, just compare senior poverty in House 5 with the State.",
                     'Don\u2019t run a t-test, just compare senior poverty in House 5 with the State.'):
            with self.subTest(text=text):
                self.assertEqual(self.convert(text, self.proposal(), None)['status'], 'propose')
                self.assertEqual(self.convert(text, self.metric(), None)['status'], 'clarify')

class Revision3PeerAndListTests(unittest.TestCase):
    """An undirected State antecedent (between/alongside) never makes the next district a comparator.
    Bare peers after a bare comparator and 'district(s) N and M' tails are comparators on every path."""
    setUpClass = classmethod(repair.LanguageRepairTests.setUpClass.__func__)
    request = repair.LanguageRepairTests.request; convert = repair.LanguageRepairTests.convert
    def held(self): return plan(H('005'), [profile(['median_age'])])
    def run_(self, text, d, confirmed):
        try:out = self.convert(text, d, confirmed)
        except repair.LanguageError as e:return ('refused', e.code)
        return (out['status'], out['clarify_field'], [c['value'] for c in out['choices']])
    def g(self, *nums): return [f'HI-{ch}-{n:03}-2024' for n in nums for ch in ('HOUSE', 'SENATE') if ch == 'HOUSE' or n <= 25]
    def test_undirected_state_antecedent_keeps_ordinary_primary(self):
        for text in ('Show the median age gap between the State and district 7.',
                     'Put median age alongside the State and district 7.'):
            for label, confirmed in (('no plan', None), ('held H5', self.held())):
                with self.subTest(text=text, held=label):
                    self.assertEqual(self.run_(text, clarify('district', 'd_h007', 'd_s007'), confirmed),
                                     ('clarify', 'district', [{'chamber': 'house', 'code': '007'}, {'chamber': 'senate', 'code': '007'}]))
                    # The correct proposal (bare 7 as primary vs the State) asks the chamber of the primary, never a comparator.
                    out = self.run_(text, decision(p=wire(plan(H('007'), [compare('median_age', 'HI-STATE-2024')]))), confirmed)
                    self.assertEqual(out[:2], ('clarify', 'district'))
        for label, confirmed in (('no plan', None), ('held H5', self.held())):
            with self.subTest(explicit=label):
                self.assertEqual(self.run_('Compare median age between the State and House 7.',
                                           decision(p=wire(plan(H('007'), [compare('median_age', 'HI-STATE-2024')]))), confirmed)[0], 'propose')
    def test_directed_state_chains_still_make_peer_comparators(self):
        for text in ('Compare median age with Maui County and the State and district 7.',
                     'Compare median age against House 12 and the State and district 7.',
                     'Is median age higher than in the State or district 7?'):
            with self.subTest(text=text):
                self.assertEqual(self.run_(text, clarify('district', 'd_h007', 'd_s007'), self.held()), ('clarify', 'comparator', self.g(7)))
    def test_bare_peers_and_list_tails_are_comparators_on_all_paths(self):
        for text, offered, expected in (
                ('Compare median age against district 6 or district 9.', ('d_h009', 'd_s009'), self.g(9)),
                ('Compare median age against district 6 or district 9.', ('d_h006', 'd_s006', 'd_h009', 'd_s009'), self.g(6, 9)),
                ('Compare median age against district 6 and 9.', ('d_h009',), self.g(9)),
                ('Median age versus districts 6 and 30?', ('d_h006', 'd_s006', 'd_h030'), self.g(6, 30)),
                ('Median age relative to district 6, 9 or 11.', ('d_h011', 'd_s011'), self.g(11))):
            for label, confirmed in (('held H5', self.held()), ('no plan explicit primary', None)):
                t = text if confirmed else re.sub('median age', 'House 2 median age', text, count=1, flags=re.I)
                with self.subTest(path='clarify', text=t, offered=offered):
                    self.assertEqual(self.run_(t, clarify('district', *offered), confirmed), ('clarify', 'comparator', expected))
        nums = (6, 9)
        for text in ('Compare median age against district 6 or district 9.', 'Compare median age against districts 6 and 9.',
                     'Compare median age against district 6 and 9.'):
            with self.subTest(path='propose', text=text):
                guessed = [profile(['median_age'])] + [compare('median_age', f'HI-HOUSE-{n:03}-2024', f's{i+2}') for i, n in enumerate(nums)]
                self.assertEqual(self.run_(text, decision(p=wire(plan(H('005'), guessed))), self.held()), ('clarify', 'comparator', self.g(*nums)))
                dropped = [profile(['median_age']), compare('median_age', 'HI-STATE-2024', 's2')]
                self.assertEqual(self.run_(text, decision(p=wire(plan(H('005'), dropped))), self.held()), ('clarify', 'comparator', self.g(*nums)))
                moved = [profile(['median_age']), compare('median_age', 'HI-HOUSE-006-2024', 's2')]
                self.assertEqual(self.run_(text, decision(p=wire(plan(H('009'), moved))), self.held())[0], 'refused')
    def test_ordinary_lists_and_navigation_keep_district_choices(self):
        all4 = ('d_h006', 'd_s006', 'd_h009', 'd_s009')
        for text in ('Profile districts 6 and 9.', 'Switch to district 6 or district 9.',
                     'Compare district 6 and district 9 with the State.', 'Show district 6 and 9 between the State and Maui County.'):
            with self.subTest(text=text):
                self.assertEqual(self.run_(text, clarify('district', *all4), self.held())[:2], ('clarify', 'district'))

class Revision3SignificanceFalsePositiveTests(unittest.TestCase):
    """A "don't/can't/won't test" phrase is not a t-test, and "significant at-risk" is not a significance level."""
    setUpClass = classmethod(repair.LanguageRepairTests.setUpClass.__func__)
    request = repair.LanguageRepairTests.request; convert = repair.LanguageRepairTests.convert
    def test_test_verbs_and_at_risk_are_not_significance(self):
        prop = decision(p=wire(plan(H('005'), [compare('poverty_rate_65_plus', 'HI-STATE-2024')])))
        for text in ("Don't test anything yet; compare senior poverty in House 5 with the State.",
                     'Don\u2019t test anything yet; compare senior poverty in House 5 with the State.',
                     "We can't test that; compare senior poverty in House 5 with the State.",
                     "We won't test it; compare senior poverty in House 5 with the State.",
                     'Seniors are a significant at-risk group; compare senior poverty in House 5 with the State.'):
            with self.subTest(text=text):self.assertEqual(self.convert(text, prop, None)['status'], 'propose')
        for text in ('Run a t-test of House 5 senior poverty versus the State.', 'Run a t test on House 5 versus the State.',
                     'Is House 5 senior poverty significant at the 90% level versus the State?', 'Is it significant at p < 0.05 for House 5 versus the State?'):
            with self.subTest(text=text):self.assertEqual(self.convert(text, prop, None)['status'], 'unsupported')

class Revision4ZeroPaddedAndAdjacencyTests(unittest.TestCase):
    """Zero-padded list tails keep their full number. "Next to" is adjacency, not a directed State cue.
    Role evaluation keeps no module-level memo of question text."""
    setUpClass = classmethod(repair.LanguageRepairTests.setUpClass.__func__)
    request = repair.LanguageRepairTests.request; convert = repair.LanguageRepairTests.convert
    def held(self): return plan(H('005'), [profile(['median_age'])])
    def run_(self, text, d, confirmed):
        try:out = self.convert(text, d, confirmed)
        except repair.LanguageError as e:return ('refused', e.code)
        return (out['status'], out['clarify_field'], [c['value'] for c in out['choices']])
    def g(self, *nums): return [f'HI-{ch}-{n:03}-2024' for n in nums for ch in ('HOUSE', 'SENATE')]
    def test_zero_padded_list_tails_on_clarify_guess_and_drop_paths(self):
        for text, nums in (('Compare median age against districts 005 and 012.', (5, 12)),
                           ('Compare median age against district 10 or 012.', (10, 12)),
                           ('Median age versus districts 03, 007 and 011?', (3, 7, 11))):
            every = [f'd_{c}{n:03}' for n in nums for c in 'hs']
            last = [f'd_h{nums[-1]:03}', f'd_s{nums[-1]:03}']
            for label, d, confirmed, expected in (
                    ('clarify all', clarify('district', *every), self.held(), self.g(*nums)),
                    ('clarify last', clarify('district', *last), self.held(), self.g(nums[-1])),
                    ('no plan explicit primary', clarify('district', *every), None, self.g(*nums)),
                    ('guess', decision(p=wire(plan(H('005'), [profile(['median_age'])] + [compare('median_age', f'HI-HOUSE-{n:03}-2024', f's{i+2}') for i, n in enumerate(nums)]))), self.held(), self.g(*nums)),
                    ('drop', decision(p=wire(plan(H('005'), [profile(['median_age']), compare('median_age', 'HI-STATE-2024', 's2')]))), self.held(), self.g(*nums))):
                t = text if confirmed else re.sub('median age', 'House 2 median age', text, count=1, flags=re.I)
                with self.subTest(text=t, path=label):
                    self.assertEqual(self.run_(t, d, confirmed), ('clarify', 'comparator', expected))
    def test_zero_padded_ordinary_primary_and_next_to_keep_district_choices(self):
        dist = lambda *a: [{'chamber': 'house' if x[2] == 'h' else 'senate', 'code': x[3:]} for x in a]
        for text, offered in (('Profile districts 005 and 012.', ('d_h005', 'd_s005', 'd_h012', 'd_s012')),
                              ('Switch to district 012.', ('d_h012', 'd_s012')),
                              ('Show median age next to the State and district 10.', ('d_h010', 'd_s010'))):
            with self.subTest(text=text):
                self.assertEqual(self.run_(text, clarify('district', *offered), self.held()), ('clarify', 'district', dist(*offered)))
        # Directed State cues still make the following district a comparator.
        for text in ('Show median age with the State and district 10.', 'Show median age compared to the State and district 10.'):
            with self.subTest(text=text):
                self.assertEqual(self.run_(text, clarify('district', 'd_h010', 'd_s010'), self.held()), ('clarify', 'comparator', self.g(10)))
    def test_role_evaluation_keeps_no_module_level_memo(self):
        from districtbrief import ia_language
        self.convert('Compare median age against district 6 or district 9.', clarify('district', 'd_h009', 'd_s009'), self.held())
        self.assertEqual([n for n, v in vars(ia_language).items() if hasattr(v, 'cache_info')], [])

class LiteralAddBootstrapTests(unittest.TestCase):
    def test_add_program_for_district_without_plan_matches_program_form(self):
        for verb in ('add', 'program'):
            status, plan, reading = interpret(f'{verb} med-quest for senate 4', None)
            self.assertEqual(status, 'ok', verb)
            self.assertEqual((plan['district']['chamber'], plan['district']['code'], plan['issue_id']), ('senate', '004', 'custom'))
            self.assertEqual(plan['steps'], [{'step_id': 's1', 'operation': 'program_evidence', 'args': {'program_ids': ['medquest_hi']}}])
            self.assertEqual({f['field'] for f in reading['matched_fields']}, {'district', 'program_id'})
        self.assertEqual(interpret('add snap for senate 30', None)[0], 'unsupported')
        self.assertEqual(interpret('add snap', None)[0], 'clarification')  # no district stated, no plan: unchanged
        status, plan, _ = interpret('add snap for house 5', recipe(H('028')))
        self.assertEqual((status, plan['district']['code'], plan['steps'][-1]['args']), ('ok', '005', {'program_ids': ['snap_hi']}))

if __name__ == '__main__':
    unittest.main()

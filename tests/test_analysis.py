import unittest
from fractions import Fraction as F
from itertools import product

from trial.archive import TrialArchive
from trial.codec import canonical_json, encode_fraction
from tests.test_preparation import records


def enumerate_distribution(probabilities, responses):
    result = {}
    for arms in product('AB', repeat=len(responses)):
        mass = F(1)
        for position, arm in enumerate(arms):
            a_mass = probabilities[position]
            mass *= a_mass if arm == 'A' else 1 - a_mass
        successes_a = sum(y for arm, y in zip(arms, responses, strict=True) if arm == 'A')
        successes_b = sum(y for arm, y in zip(arms, responses, strict=True) if arm == 'B')
        if mass:
            statistic = successes_a - successes_b
            result[statistic] = result.get(statistic, F(0)) + mass
    return result


class TestFixedAnalysis(unittest.TestCase):
    def setUp(self):
        self.archive = TrialArchive.open(':memory:')
        self.addCleanup(self.archive.close)

    def _trial(self, probabilities, assignments, responses):
        design = self.archive.save_design('plan', probabilities)
        return self.archive.save_trial('day', design, records(assignments, responses))

    def _outcome_counts(self):
        return self.archive.connection.execute(
            'SELECT (SELECT count(*) FROM bindings), (SELECT count(*) FROM replays), (SELECT count(*) FROM reports)'
        ).fetchone()

    def test_four_successes(self):
        trial = self._trial([F(1, 2)] * 4, 'AAAA', [1] * 4)
        replay = self.archive.replay.replay_fixed(trial.key)
        report = self.archive.inference.test_fixed(replay.id)
        self.assertEqual(replay.step_probabilities, (F(1, 2),) * 4)
        self.assertEqual(replay.path_probability, F(1, 16))
        self.assertEqual(replay.statistic, 4)
        self.assertEqual(report.observed_statistic, 4)
        self.assertEqual(report.tail_mass, F(1, 8))
        self.assertEqual(report.distribution, {-4: F(1, 16), -2: F(1, 4), 0: F(3, 8), 2: F(1, 4), 4: F(1, 16)})
        self.assertEqual(report.replay_id, replay.id)
        self.assertEqual(self.archive.read_report(report.id), report)

    def test_unequal_schedule(self):
        probabilities = (F(1, 3), F(2, 3))
        replay, report = self.archive.analyze_fixed(self._trial(probabilities, 'AA', (1, 1)))
        expected_distribution = {-2: F(2, 9), 0: F(5, 9), 2: F(2, 9)}
        self.assertEqual(replay.statistic, 2)
        self.assertEqual(replay.path_probability, F(2, 9))
        self.assertEqual(report.tail_mass, F(4, 9))
        self.assertEqual(report.distribution, expected_distribution)
        self.assertEqual(sum(report.distribution.values(), F(0)), F(1))
        saved = self.archive.read_report(report.id)
        self.assertEqual(saved, report)
        print('POINTWISE_SCENARIO ' + canonical_json({
            'case_id': 'v3',
            'input': {'p_a': [encode_fraction(p) for p in probabilities], 'assignments': 'AA', 'responses': [1, 1]},
            'expected': {'path': ['2', '9'], 'statistic': 2},
            'actual': {'path': encode_fraction(replay.path_probability), 'statistic': replay.statistic},
            'downstream_expected': {'distribution': [[-2, ['2', '9']], [0, ['5', '9']], [2, ['2', '9']]],
                                    'tail': ['4', '9']},
            'downstream_actual': {'distribution': [[s, encode_fraction(m)] for s, m in saved.distribution.items()],
                                  'tail': encode_fraction(saved.tail_mass)},
            'code_paths': ['trial/schedule.py', 'trial/replay.py', 'trial/distribution.py', 'trial/report_store.py'],
            'oracle': 'The four paths AA, AB, BA and BB have masses 2/9, 1/9, 4/9 and 2/9.'}))

    def test_zero_probability_assignment(self):
        trial = self._trial((0, 1), 'AA', (0, 1))
        with self.assertRaisesRegex(ValueError, 'position 1'):
            self.archive.replay_fixed(trial)
        self.assertEqual(self._outcome_counts(), (0, 0, 0))

    def test_mixed_responses(self):
        design = self.archive.save_design('fair', [F(1, 2)] * 4)
        for arms, expected in [('ABAB', 2), ('BABA', -2)]:
            with self.subTest(arms=arms):
                trial = self.archive.save_trial('day', design, records(arms, (1, 0, 1, 0)))
                replay, report = self.archive.analyze_fixed(trial)
                self.assertEqual(replay.step_probabilities, (F(1, 2),) * 4)
                self.assertEqual(replay.path_probability, F(1, 16))
                self.assertEqual((replay.statistic, report.observed_statistic), (expected, expected))
                self.assertEqual(report.distribution, {-2: F(1, 4), 0: F(1, 2), 2: F(1, 4)})
                self.assertEqual(report.tail_mass, F(1, 2))

    def test_inclusive_boundary(self):
        replay, report = self.archive.analyze_fixed(self._trial([F(1, 2)] * 4, 'BBBB', [1] * 4))
        self.assertEqual(replay.statistic, -4)
        self.assertEqual(report.tail_mass, F(1, 8))
        replay, report = self.archive.analyze_fixed(self._trial([F(1, 2)] * 4, 'ABAB', [0] * 4))
        self.assertEqual(replay.statistic, 0)
        self.assertEqual(report.distribution, {0: F(1)})
        self.assertEqual(report.tail_mass, F(1))

    def test_actual_b(self):
        replay, report = self.archive.analyze_fixed(self._trial((F(1, 3), F(2, 3)), 'AB', (1, 1)))
        self.assertEqual(replay.step_probabilities, (F(1, 3), F(1, 3)))
        self.assertEqual(replay.path_probability, F(1, 9))
        self.assertEqual(replay.statistic, 0)
        self.assertEqual(report.tail_mass, F(1))

    def test_weighted_distribution(self):
        plan = (F(1, 3), F(2, 3))
        _, report = self.archive.analyze_fixed(self._trial(plan, 'AA', (1, 1)))
        self.assertEqual(report.distribution, {-2: F(2, 9), 0: F(5, 9), 2: F(2, 9)})
        for probabilities, responses, arms in [(plan, (1, 1), 'AA'),
                                                ((F(2, 3), F(3, 5), F(1, 4)), (0, 1, 1), 'BAB'),
                                                ((F(0), F(2, 7), F(1)), (1, 1, 0), 'BAA')]:
            with self.subTest(probabilities=probabilities, responses=responses):
                replay, report = self.archive.analyze_fixed(self._trial(probabilities, arms, responses))
                oracle = enumerate_distribution(probabilities, responses)
                self.assertEqual(report.distribution, oracle)
                inside = sum((m for s, m in oracle.items() if -abs(replay.statistic) < s < abs(replay.statistic)), F(0))
                self.assertEqual(report.tail_mass, 1 - inside)

    def test_fixed_response_identity(self):
        replay, report = self.archive.analyze_fixed(self._trial((F(1, 3), F(2, 3)), 'AB', (1, 0)))
        self.assertEqual(replay.statistic, 1)
        self.assertEqual(report.distribution, {-1: F(2, 3), 1: F(1, 3)})
        self.assertEqual(report.tail_mass, F(1))

    def test_endpoint_zero(self):
        for arms, position in [('AA', 1), ('BB', 2)]:
            with self.subTest(arms=arms):
                trial = self._trial((0, 1), arms, (0, 0))
                with self.assertRaisesRegex(ValueError, f'position {position}'):
                    self.archive.analyze_fixed(trial)
                self.assertEqual(self._outcome_counts(), (0, 0, 0))
        replay, report = self.archive.analyze_fixed(self._trial((0, 1), 'BA', (1, 1)))
        self.assertEqual(replay.step_probabilities, (F(1), F(1)))
        self.assertEqual(replay.path_probability, F(1))
        self.assertEqual(report.distribution, {0: F(1)})

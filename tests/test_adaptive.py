import unittest
from fractions import Fraction as F
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory

from trial.archive import TrialArchive
from trial.publication import PublicationError, REPORT_DISTRIBUTION, REPORT_HEADER


def oracle_masses(initial_a, initial_b, horizon, min_n, boundary, responses, observed):
    """Independent short-path accounting: enumerate every counterfactual assignment
    string over the observed length, keep only paths whose first stop is exactly
    the observed length, and accumulate the raw and tail masses."""
    n = len(responses)
    stop = F(0)
    joint = F(0)
    for arms in product('AB', repeat=n):
        balls_a, balls_b, statistic, mass = initial_a, initial_b, 0, F(1)
        stopped_before = False
        for position, (arm, response) in enumerate(zip(arms, responses), 1):
            mass *= F(balls_a if arm == 'A' else balls_b, balls_a + balls_b)
            if response == 1:
                if arm == 'A':
                    balls_a += 1
                    statistic += 1
                else:
                    balls_b += 1
                    statistic -= 1
            elif arm == 'A':
                balls_b += 1
            else:
                balls_a += 1
            if position < n and position >= min_n and abs(statistic) >= boundary:
                stopped_before = True
                break
        if stopped_before:
            continue
        if not ((position >= min_n and abs(statistic) >= boundary) or position == horizon):
            continue
        stop += mass
        if abs(statistic) >= abs(observed):
            joint += mass
    return stop, joint


def oracle_path(initial_a, initial_b, responses, assignments):
    """Independent replay of the actual record: per-step probabilities and statistic."""
    balls_a, balls_b, statistic, mass = initial_a, initial_b, 0, F(1)
    before = []
    for arm, response in zip(assignments, responses, strict=True):
        before.append((balls_a, balls_b))
        mass *= F(balls_a if arm == 'A' else balls_b, balls_a + balls_b)
        if response == 1:
            if arm == 'A':
                balls_a += 1
                statistic += 1
            else:
                balls_b += 1
                statistic -= 1
        elif arm == 'A':
            balls_b += 1
        else:
            balls_a += 1
    return before, mass, statistic


class TestAdaptiveDesign(unittest.TestCase):
    def setUp(self):
        self.archive = TrialArchive.open(':memory:')
        self.addCleanup(self.archive.close)

    def test_save_and_identity(self):
        first = self.archive.save_adaptive(1, 1, 4, 4, 4)
        second = self.archive.save_adaptive(1, 1, 4, 4, 4)
        third = self.archive.save_adaptive(2, 3, 6, 2, 2)
        self.assertEqual((first, second, third), (1, 2, 3))
        self.assertTrue(all(type(identity) is int for identity in (first, second, third)))

    def test_invalid_parameters(self):
        bad = [
            (0, 1, 4, 2, 2), (1, 0, 4, 2, 2), (-1, 1, 4, 2, 2), (1, 1, 4, 2, 0),
            (1, 1, 4, 1, 2), (1, 1, 4, 5, 2), (1, 1, 3, 4, 2), (1, 1, 19, 2, 2),
            (True, 1, 4, 2, 2), (1, False, 4, 2, 2), (1, 1, True, 2, 2),
            (1, 1, 4, True, 2), (1, 1, 4, 2, True), (1.0, 1, 4, 2, 2),
            (1, 1, 4, 2, None), ('1', 1, 4, 2, 2), (1, 1, 4, 2, 2.5),
        ]
        for parameters in bad:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                self.archive.save_adaptive(*parameters)
        self.assertEqual(
            self.archive.connection.execute('SELECT count(*) FROM adaptive_designs').fetchone(), (0,))

    def test_boundaries(self):
        self.assertEqual(self.archive.save_adaptive(1, 1, 2, 2, 1), 1)
        self.assertEqual(self.archive.save_adaptive(9, 9, 18, 18, 18), 2)


class TestAdaptiveReplay(unittest.TestCase):
    def setUp(self):
        self.archive = TrialArchive.open(':memory:')
        self.addCleanup(self.archive.close)
        self.design_id = self.archive.save_adaptive(1, 1, 4, 2, 2)

    def _counts(self):
        return self.archive.connection.execute(
            'SELECT (SELECT count(*) FROM adaptive_replays), (SELECT count(*) FROM adaptive_replay_steps),'
            ' (SELECT count(*) FROM adaptive_reports)'
        ).fetchone()

    def test_walk_and_handoff(self):
        replay = self.archive.replay_adaptive(self.design_id, [1, 1, 1, 1], 'ABAA')
        before, mass, statistic = oracle_path(1, 1, (1, 1, 1, 1), 'ABAA')
        self.assertEqual(replay['design_id'], self.design_id)
        self.assertEqual(replay['design'], {'initial_a': 1, 'initial_b': 1, 'horizon': 4, 'min_n': 2, 'boundary': 2})
        self.assertEqual(replay['responses'], [1, 1, 1, 1])
        self.assertEqual(replay['assignments'], ['A', 'B', 'A', 'A'])
        self.assertEqual([step['position'] for step in replay['steps']], [1, 2, 3, 4])
        self.assertEqual([tuple(step['before']) for step in replay['steps']], before)
        self.assertEqual([step['statistic'] for step in replay['steps']], [1, 0, 1, 2])
        self.assertEqual(replay['steps'][0]['probability'], F(1, 2))
        self.assertEqual(replay['steps'][1]['probability'], F(1, 3))
        self.assertEqual(replay['steps'][2]['probability'], F(1, 2))
        self.assertEqual(replay['steps'][3]['probability'], F(3, 5))
        self.assertEqual(replay['path_probability'], mass)
        self.assertEqual(replay['statistic'], statistic)
        self.assertEqual(self.archive.read_adaptive_replay(replay['id']), replay)

    def test_assignment_forms(self):
        as_list = self.archive.replay_adaptive(self.design_id, (1, 1, 1, 1), ['A', 'B', 'A', 'A'])
        as_tuple = self.archive.replay_adaptive(self.design_id, (1, 1, 1, 1), ('A', 'B', 'A', 'A'))
        as_string = self.archive.replay_adaptive(self.design_id, (1, 1, 1, 1), 'ABAA')
        self.assertEqual(as_list['steps'], as_tuple['steps'])
        self.assertEqual(as_list['steps'], as_string['steps'])
        self.assertEqual(as_list['assignments'], ['A', 'B', 'A', 'A'])

    def test_invalid_records_rejected_atomically(self):
        bad = [
            ((1,), 'A'),                          # ends before any stop
            ((1, 1, 1), 'ABA'),                   # ends before any stop
            ((1, 1, 1, 1, 1), 'AAAAA'),           # continues past the horizon
            ((1, 1, 1, 1), 'AAAA'),               # continues past the first stop at 2
            ((1, 1, 1, 1), 'ABAC'),               # illegal arm
            ((1, 1, 1, 2), 'ABAA'),               # illegal response
            ((1, 1, 1, True), 'ABAA'),            # boolean response
            ((1, 1, 1), 'ABAA'),                  # length mismatch
            ((), ''),                             # empty record
            ('1111', 'ABAA'),                     # responses not a list or tuple
            ((1, 1, 1, 1), 5),                    # illegal assignments container
            ((1, 1, 1, 1), ['A', 'B', 'A', 'a']), # illegal arm in list
        ]
        for responses, assignments in bad:
            with self.subTest(responses=responses, assignments=assignments):
                with self.assertRaises(ValueError):
                    self.archive.replay_adaptive(self.design_id, responses, assignments)
                self.assertEqual(self._counts(), (0, 0, 0))
        with self.assertRaises(KeyError):
            self.archive.replay_adaptive(9999, (1, 1, 1, 1), 'ABAA')
        for identity in (True, 0, -1, '1', 1.5, None):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.archive.replay_adaptive(identity, (1, 1, 1, 1), 'ABAA')
        self.assertEqual(self._counts(), (0, 0, 0))

    def test_stopping_rules(self):
        # boundary stop exactly at min_n
        replay = self.archive.replay_adaptive(self.design_id, (1, 1), 'AA')
        self.assertEqual(replay['statistic'], 2)
        # horizon stop without reaching the boundary
        replay = self.archive.replay_adaptive(self.design_id, (1, 0, 0, 1), 'ABAB')
        self.assertEqual(replay['statistic'], 0)
        # a record that passes a boundary stop earlier must be rejected
        with self.assertRaisesRegex(ValueError, 'stopping time'):
            self.archive.replay_adaptive(self.design_id, (1, 1, 1, 1), 'AABB')


class TestAdaptiveInference(unittest.TestCase):
    CASES = (
        ((1, 1, 4, 4, 4), (1, 1, 1, 1), 'AAAA', (F(1, 5), 4, F(1), F(2, 5), F(2, 5))),
        ((1, 1, 6, 4, 4), (1, 1, 1, 1), 'AAAA', (F(1, 5), 4, F(2, 5), F(2, 5), F(1))),
        ((1, 1, 4, 2, 2), (1, 1, 1, 1), 'ABAA', (F(1, 20), 2, F(1, 3), F(1, 5), F(3, 5))),
        ((1, 1, 4, 2, 2), (1, 0, 1, 1), 'ABBA', (F(1, 40), 1, F(5, 12), F(5, 12), F(1))),
        ((1, 1, 4, 4, 4), (1, 1, 1, 0), 'AAAA', (F(1, 5), 3, F(1), F(1, 2), F(1, 2))),
    )

    def setUp(self):
        self.archive = TrialArchive.open(':memory:')
        self.addCleanup(self.archive.close)

    def test_hand_calculated_cases(self):
        for design, responses, assignments, expected in self.CASES:
            with self.subTest(design=design, assignments=assignments, responses=responses):
                design_id = self.archive.save_adaptive(*design)
                replay = self.archive.replay_adaptive(design_id, responses, assignments)
                report = self.archive.test_adaptive(replay['id'])
                actual = (replay['path_probability'], replay['statistic'], report['stop_mass'],
                          report['joint_tail_mass'], report['conditional_tail'])
                self.assertEqual(actual, expected)
                self.assertEqual(report['replay_id'], replay['id'])
                self.assertEqual(report['observed_statistic'], replay['statistic'])
                self.assertEqual(self.archive.read_adaptive_report(report['id']), report)

    def test_independent_short_path_accounting(self):
        designs = [(1, 1, 4, 2, 2), (1, 1, 5, 3, 2), (2, 1, 4, 2, 3), (1, 2, 5, 4, 2),
                   (3, 2, 6, 2, 2), (1, 1, 6, 6, 1), (2, 3, 5, 5, 4)]
        records = ['AB', 'BA', 'AAB', 'ABB', 'ABBA', 'BAAB', 'AAAB', 'BBBB', 'ABAB', 'BABA',
                   'AABB', 'BBAA', 'AAA', 'BBB', 'ABAAB', 'BABBA']
        checked = 0
        for design in designs:
            design_id = self.archive.save_adaptive(*design)
            horizon = design[2]
            for arms in records:
                for responses in product((0, 1), repeat=len(arms)):
                    try:
                        replay = self.archive.replay_adaptive(design_id, responses, arms)
                    except ValueError:
                        continue
                    report = self.archive.test_adaptive(replay['id'])
                    stop, joint = oracle_masses(*design, responses, replay['statistic'])
                    self.assertEqual(report['stop_mass'], stop)
                    self.assertEqual(report['joint_tail_mass'], joint)
                    self.assertEqual(report['conditional_tail'], joint / stop)
                    checked += 1
        self.assertGreater(checked, 200)

    def test_handoff_invariants(self):
        design = (2, 1, 5, 3, 2)
        design_id = self.archive.save_adaptive(*design)
        for arms, responses in [('ABBAA', (1, 0, 1, 1, 1)), ('BAAAA', (1, 1, 0, 1, 1)), ('AAB', (1, 1, 0))]:
            with self.subTest(arms=arms, responses=responses):
                replay = self.archive.replay_adaptive(design_id, responses, arms)
                report = self.archive.test_adaptive(replay['id'])
                # the replay hands the test one termination event: both masses count
                # exactly the paths that first stop at the observed length
                self.assertEqual(report['replay_id'], replay['id'])
                self.assertEqual(report['observed_statistic'], replay['statistic'])
                self.assertLessEqual(report['joint_tail_mass'], report['stop_mass'])
                self.assertEqual(report['conditional_tail'] * report['stop_mass'], report['joint_tail_mass'])
                # the actual path always belongs to its own stop-length event
                self.assertLessEqual(replay['path_probability'], report['stop_mass'])
                self.assertLessEqual(replay['path_probability'], report['joint_tail_mass'])
                self.assertLessEqual(report['stop_mass'], F(1))
                self.assertGreater(report['joint_tail_mass'], F(0))

    def test_unknown_replay(self):
        with self.assertRaises(KeyError):
            self.archive.test_adaptive(9999)
        for identity in (True, 0, -2, '1', 2.5, None):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.archive.test_adaptive(identity)


class TestAdaptiveReview(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'adaptive.sqlite'
        self.archive = TrialArchive.open(self.path)
        self.addCleanup(self.archive.close)
        self.design_id = self.archive.save_adaptive(1, 1, 4, 2, 2)
        self.replay = self.archive.replay_adaptive(self.design_id, [1, 1, 1, 1], 'ABAA')
        self.report = self.archive.test_adaptive(self.replay['id'])

    def _state(self, archive):
        tables = ('adaptive_designs', 'adaptive_replays', 'adaptive_replay_steps', 'adaptive_reports')
        return tuple(archive.connection.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall()
                     for table in tables)

    def test_read_identities(self):
        for identity in (True, 0, -1, '1', 1.5, None):
            with self.subTest(identity=identity):
                with self.assertRaises(ValueError):
                    self.archive.read_adaptive_replay(identity)
                with self.assertRaises(ValueError):
                    self.archive.read_adaptive_report(identity)
        with self.assertRaises(KeyError):
            self.archive.read_adaptive_replay(9999)
        with self.assertRaises(KeyError):
            self.archive.read_adaptive_report(9999)

    def test_inputs_and_outputs_are_detached(self):
        responses = [1, 0, 1, 1]
        replay = self.archive.replay_adaptive(self.design_id, responses, list('ABBA'))
        responses[0] = 0
        replay['steps'].clear()
        replay['responses'][0] = 0
        replay['statistic'] = -99
        saved = self.archive.read_adaptive_replay(replay['id'])
        self.assertEqual(saved['responses'], [1, 0, 1, 1])
        self.assertEqual(len(saved['steps']), 4)
        self.assertEqual(saved['statistic'], 1)
        saved['steps'].clear()
        self.assertEqual(len(self.archive.read_adaptive_replay(replay['id'])['steps']), 4)

    def test_correction_keeps_original(self):
        corrected = self.archive.replay_adaptive(self.design_id, (1, 0, 1, 1), 'ABBA')
        corrected_report = self.archive.test_adaptive(corrected['id'])
        self.assertNotEqual(corrected['id'], self.replay['id'])
        self.assertEqual(corrected['design_id'], self.design_id)
        self.assertEqual(self.archive.read_adaptive_replay(self.replay['id']), self.replay)
        self.assertEqual(self.archive.read_adaptive_report(self.report['id']), self.report)
        self.assertEqual(corrected_report['conditional_tail'], F(1))
        other_design = self.archive.save_adaptive(1, 1, 4, 4, 4)
        moved = self.archive.replay_adaptive(other_design, (1, 1, 1, 0), 'AAAA')
        self.assertEqual(self.archive.test_adaptive(moved['id'])['conditional_tail'], F(1, 2))
        self.assertEqual(self.archive.read_adaptive_report(self.report['id']), self.report)

    def test_reopen(self):
        self.archive.close()
        with TrialArchive.open(self.path) as reopened:
            self.assertEqual(reopened.read_adaptive_replay(self.replay['id']), self.replay)
            self.assertEqual(reopened.read_adaptive_report(self.report['id']), self.report)
            again = reopened.test_adaptive(self.replay['id'])
            self.assertEqual(again['stop_mass'], self.report['stop_mass'])
        self.archive = TrialArchive.open(self.path)
        self.addCleanup(self.archive.close)

    def test_publication_rollback(self):
        replay = self.archive.replay_adaptive(self.design_id, (1, 0, 1, 1), 'ABBA')
        for stage in (REPORT_HEADER, REPORT_DISTRIBUTION):
            with self.subTest(stage=stage):
                before = self._state(self.archive)
                with self.archive.publication.fail_at(stage), self.assertRaisesRegex(PublicationError, stage):
                    self.archive.test_adaptive(replay['id'])
                self.assertEqual(self._state(self.archive), before)
                self.assertFalse(self.archive.connection.in_transaction)
                self.assertEqual(self.archive.read_adaptive_replay(self.replay['id']), self.replay)
                self.assertEqual(self.archive.read_adaptive_report(self.report['id']), self.report)
                report = self.archive.test_adaptive(replay['id'])
                self.assertEqual(report['stop_mass'], F(5, 12))
                self.assertEqual(self.archive.read_adaptive_report(report['id']), report)

    def test_failed_replay_publishes_nothing(self):
        before = self._state(self.archive)
        with self.assertRaises(ValueError):
            self.archive.replay_adaptive(self.design_id, (1, 1, 1, 1), 'AAAA')
        self.assertEqual(self._state(self.archive), before)


class TestAdaptiveMigration(unittest.TestCase):
    def test_old_database_opens_and_keeps_fixed_outcomes(self):
        from tests.test_preparation import records
        from fractions import Fraction as F
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'trial.sqlite'
            with TrialArchive.open(database) as archive:
                design = archive.save_design('fair', [F(1, 2)] * 4)
                trial = archive.save_trial('day', design, records())
                _, report = archive.analyze_fixed(trial)
                for table in ('adaptive_designs', 'adaptive_replays', 'adaptive_replay_steps', 'adaptive_reports'):
                    archive.connection.execute(f'DROP TABLE {table}')
            with TrialArchive.open(database) as archive:
                self.assertEqual(archive.read_report(report.id), report)
                design_id = archive.save_adaptive(1, 1, 4, 4, 4)
                replay = archive.replay_adaptive(design_id, (1, 1, 1, 1), 'AAAA')
                adaptive_report = archive.test_adaptive(replay['id'])
                self.assertEqual(adaptive_report['conditional_tail'], F(2, 5))
            with TrialArchive.open(database) as archive:
                self.assertEqual(archive.read_report(report.id), report)
                self.assertEqual(archive.read_adaptive_report(adaptive_report['id']), adaptive_report)
                self.assertEqual(archive.read_adaptive_replay(replay['id']), replay)


if __name__ == '__main__':
    unittest.main()

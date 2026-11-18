import unittest
from dataclasses import replace
from fractions import Fraction as F

from trial.archive import TrialArchive
from trial.revisions import BatchRecord


def records(assignments='AAAA', responses=(1, 1, 1, 1)):
    return [BatchRecord(f'batch-{position}', position, arm, response)
            for position, (arm, response) in enumerate(zip(assignments, responses, strict=True), 1)]


class TestPreparation(unittest.TestCase):
    def setUp(self):
        self.archive = TrialArchive.open(':memory:')
        self.addCleanup(self.archive.close)

    def _counts(self):
        return self.archive.connection.execute(
            'SELECT (SELECT count(*) FROM trial_revisions), (SELECT count(*) FROM batch_records)'
        ).fetchone()

    def test_complete_trial(self):
        design = self.archive.save_design('fair', [F(1, 2)] * 4)
        rows = records()
        trial = self.archive.save_trial('day', design, rows)
        self.assertEqual(design.key, ('fair', 1))
        self.assertEqual(trial.key, ('day', 1))
        self.assertEqual(trial.design_key, design.key)
        self.assertEqual(self.archive.read_trial(trial.key).records, tuple(rows))
        self.assertEqual(self.archive.read_design(trial.design_key), design)

    def test_duplicate_and_missing_positions(self):
        design = self.archive.save_design('fair', [F(1, 2)] * 4)
        rows = records()
        old = self.archive.save_trial('day', design, rows)
        with self.assertRaisesRegex(ValueError, 'duplicate batch ID'):
            self.archive.save_trial('day', design, [rows[0], replace(rows[1], batch_id=rows[0].batch_id), *rows[2:]])
        with self.assertRaisesRegex(ValueError, 'record count'):
            self.archive.save_trial('day', design, rows[:3])
        self.assertEqual(self._counts(), (1, 4))
        self.assertEqual(self.archive.read_trial(old.key), old)

    def test_design_roundtrip(self):
        probabilities = [F(2, 3), F(1, 3)]
        first = self.archive.design.save_design('plan', probabilities)
        probabilities.reverse()
        second = self.archive.save_design('plan', [F(1, 4), F(3, 4)])
        first_read = self.archive.read_design(first.key)
        second_read = self.archive.read_design(second.key)
        self.assertEqual((first.key, second.key), (('plan', 1), ('plan', 2)))
        self.assertEqual(first_read.schedule.probabilities, (F(2, 3), F(1, 3)))
        self.assertEqual(first_read.schedule.probability_at(1), F(2, 3))
        self.assertEqual(first_read.schedule.probability_at(2), F(1, 3))
        self.assertEqual(second_read.schedule.probabilities, (F(1, 4), F(3, 4)))

    def test_design_boundaries(self):
        first = self.archive.save_design('ends', [0])
        second = self.archive.save_design('ends', [0, 1] * 9)
        self.assertEqual(first.schedule.probabilities, (F(0),))
        self.assertEqual(second.schedule.probabilities, (F(0), F(1)) * 9)
        for identity, probabilities in [('', [0]), ('  ', [0]), (None, [0]), ('ends', []),
                                        ('ends', [0] * 19), ('ends', [F(-1, 2)]), ('ends', [F(5, 4)]),
                                        ('ends', [True]), ('ends', [0.5]), ('ends', [None]), ('ends', '1')]:
            with self.subTest(identity=identity, probabilities=probabilities), self.assertRaises(ValueError):
                self.archive.save_design(identity, probabilities)
        self.assertEqual(self.archive.read_design(first.key), first)
        self.assertEqual(self.archive.read_design(second.key), second)
        self.assertEqual(self.archive.connection.execute('SELECT count(*) FROM design_probabilities').fetchone(), (19,))
        self.assertEqual(self.archive.save_design('ends', [1]).revision, 3)

    def test_record_identity(self):
        design = self.archive.save_design('fair', [F(1, 2)] * 4)
        rows = [{'batch_id': b, 'position': i, 'assignment': a, 'response': y}
                for i, (b, a, y) in enumerate(zip('ZAMB', 'ABAB', [1, 0, 1, 0], strict=True), 1)]
        expected = tuple(BatchRecord(**row) for row in rows)
        trial = self.archive.observations.save_trial('day', design.key, rows)
        rows[0]['response'] = 0
        rows.reverse()
        self.assertEqual(trial.records, expected)
        self.assertEqual(self.archive.read_trial(trial.key).records, expected)

    def test_atomic_batch(self):
        design = self.archive.save_design('fair', [F(1, 2)] * 4)
        rows = records()
        first = self.archive.save_trial('day', design, rows)
        cases = [[rows[0], replace(rows[1], batch_id=rows[0].batch_id), *rows[2:]],
                 [rows[0], replace(rows[1], position=1), *rows[2:]], rows[:3]]
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.archive.save_trial('day', design, invalid)
            self.assertEqual(self._counts(), (1, 4))
            self.assertEqual(self.archive.read_trial(first.key), first)
        revised = self.archive.save_trial('day', design, [*rows[:3], replace(rows[3], response=0)])
        self.assertEqual(revised.key, ('day', 2))
        self.assertEqual(self._counts(), (2, 8))

    def test_invalid_fields(self):
        design = self.archive.save_design('fair', [F(1, 2)] * 4)
        rows = records()
        candidates = [[rows[0], replace(rows[1], position=1), *rows[2:]],
                      [rows[1], rows[0], *rows[2:]],
                      [replace(rows[0], position=True), *rows[1:]],
                      [replace(rows[0], assignment='C'), *rows[1:]],
                      [replace(rows[0], batch_id=' '), *rows[1:]],
                      [replace(rows[0], response=None), *rows[1:]],
                      [replace(rows[0], response=True), *rows[1:]],
                      [{'batch_id': 'missing', 'position': 1, 'assignment': 'A'}, *rows[1:]]]
        for invalid in candidates:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.archive.save_trial('day', design, invalid)
        with self.assertRaises(KeyError):
            self.archive.save_trial('day', ('fair', 99), rows)
        self.assertEqual(self._counts(), (0, 0))

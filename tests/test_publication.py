import unittest
from fractions import Fraction as F
from pathlib import Path
from tempfile import TemporaryDirectory

from trial.archive import TrialArchive
from trial.publication import PublicationError, REPORT_DISTRIBUTION, REPORT_HEADER
from tests.test_analysis import enumerate_distribution
from tests.test_preparation import records


class TestPublication(unittest.TestCase):
    TABLES = ('bindings', 'replays', 'replay_steps', 'reports', 'report_distribution')

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'trial.sqlite'
        self.archive = TrialArchive.open(self.path)
        self.addCleanup(self.archive.close)
        self.probabilities = (F(1, 3), F(2, 3))
        design = self.archive.save_design('unequal', self.probabilities)
        self.trial = self.archive.save_trial('day', design, records('AA', (1, 1)))
        self.old_replay, self.old_report = self.archive.analyze_fixed(self.trial)

    def _state(self, archive):
        return tuple(archive.connection.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall()
                     for table in self.TABLES)

    def _assert_result(self, report, replay):
        self.assertEqual(report.replay_id, replay.id)
        self.assertEqual(replay.path_probability, F(2, 9))
        self.assertEqual(self.archive.read_binding(replay.binding_id).trial, self.trial)
        self.assertEqual(report.observed_statistic, 2)
        self.assertEqual(report.distribution, enumerate_distribution(self.probabilities, (1, 1)))
        self.assertEqual(report.tail_mass, F(4, 9))
        self.assertEqual(self.archive.read_report(report.id), report)

    def test_failed_report_retry(self):
        replay = self.archive.replay_fixed(self.trial)
        before = self._state(self.archive)
        with self.archive.publication.fail_at(REPORT_HEADER), self.assertRaisesRegex(PublicationError, REPORT_HEADER):
            self.archive.test_fixed(replay.id)
        self.assertEqual(self._state(self.archive), before)
        self.assertEqual(self.archive.read_report(self.old_report.id), self.old_report)
        self._assert_result(self.archive.test_fixed(replay.id), replay)

    def test_rollback_stages(self):
        previous_replay = self.archive.replay_fixed(self.trial)
        for stage in (REPORT_HEADER, REPORT_DISTRIBUTION):
            for joint in (False, True):
                with self.subTest(stage=stage, joint=joint):
                    before = self._state(self.archive)
                    with self.archive.publication.fail_at(stage), self.assertRaisesRegex(PublicationError, stage):
                        if joint:
                            self.archive.analyze_fixed(self.trial)
                        else:
                            self.archive.test_fixed(previous_replay.id)
                    self.assertEqual(self._state(self.archive), before)
                    self.assertFalse(self.archive.connection.in_transaction)
                    with TrialArchive.open(self.path) as reopened:
                        self.assertEqual(self._state(reopened), before)
                        self.assertEqual(reopened.read_report(self.old_report.id), self.old_report)
                        self.assertEqual(reopened.read_replay(previous_replay.id), previous_replay)
                    if joint:
                        replay, report = self.archive.analyze_fixed(self.trial)
                    else:
                        replay = previous_replay
                        report = self.archive.test_fixed(replay.id)
                    self._assert_result(report, replay)
        before = self._state(self.archive)
        with self.assertRaises(KeyError):
            self.archive.test_fixed(9999)
        self.assertEqual(self._state(self.archive), before)

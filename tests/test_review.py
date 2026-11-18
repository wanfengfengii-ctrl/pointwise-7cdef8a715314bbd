import sys
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
from fractions import Fraction as F
from pathlib import Path
from tempfile import TemporaryDirectory

from trial.archive import TrialArchive
from trial.codec import canonical_json, encode_fraction, load_json
from trial.distribution import fixed_statistic_distribution
from trial.inference import calculate_fixed_report
from trial.path_probability import actual_step_probabilities
from trial.reconciliation import verify_delivery_bundle
from trial.replay import calculate_fixed_replay
from trial.schema import initialize_schema
from trial.statistic import signed_successes
from tests.test_preparation import records


class TestReview(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'trial.sqlite'

    def _original(self, archive):
        design = archive.save_design('fair', [F(1, 2)] * 4)
        trial = archive.save_trial('day', design, records())
        replay, report = archive.analyze_fixed(trial)
        return design, trial, replay, report

    def test_correction_and_reopen(self):
        with TrialArchive.open(self.path) as archive:
            design, old_trial, old_replay, old_report = self._original(archive)
            trial = archive.save_trial('day', design, records('AAAA', (1, 1, 1, 0)))
            replay, report = archive.analyze_fixed(trial)
        with TrialArchive.open(self.path) as archive:
            self.assertEqual(archive.read_report(old_report.id), old_report)
            self.assertEqual(archive.read_report(report.id), report)
            self.assertEqual(archive.read_replay(old_report.replay_id), old_replay)
            self.assertEqual(archive.read_binding(old_replay.binding_id).trial, old_trial)
            self.assertEqual(archive.read_binding(replay.binding_id).trial, trial)
            self.assertEqual((old_report.tail_mass, report.tail_mass), (F(1, 8), F(1, 4)))
            self.assertEqual((old_report.observed_statistic, report.observed_statistic), (4, 3))
            self.assertEqual((old_replay.path_probability, replay.path_probability), (F(1, 16), F(1, 16)))

    def test_revision_lineage(self):
        with TrialArchive.open(self.path) as archive:
            original_design, old_trial, old_replay, old_report = self._original(archive)
            corrected = archive.save_trial('day', original_design.key, records('AAAA', (1, 1, 1, 0)))
            new_replay, new_report = archive.analyze_fixed(corrected)
            latest_design = archive.save_design('fair', [F(1, 4), F(3, 4)] * 2)
            self.assertEqual(latest_design.key, ('fair', 2))
        with TrialArchive.open(self.path) as archive:
            for trial, replay, report, tail, statistic, response in [
                (old_trial, old_replay, old_report, F(1, 8), 4, 1),
                (corrected, new_replay, new_report, F(1, 4), 3, 0),
            ]:
                with self.subTest(revision=trial.revision):
                    self.assertEqual(archive.read_trial(trial.key).design_key, original_design.key)
                    saved = archive.read_report(report.id)
                    self.assertEqual((saved.replay_id, saved.tail_mass, saved.observed_statistic), (replay.id, tail, statistic))
                    binding = archive.read_binding(replay.binding_id)
                    self.assertEqual((binding.design, binding.trial), (original_design, trial))
                    bundle = archive.export_report(report.id)
                    self.assertEqual(bundle['design']['probabilities'], [['1', '2']] * 4)
                    self.assertEqual(bundle['trial']['records'][-1]['response'], response)
                    self.assertEqual(verify_delivery_bundle(bundle).tail_mass, tail)

    def test_detached_read(self):
        with TrialArchive.open(self.path) as archive:
            _, _, _, original = self._original(archive)
            monitored = {function.__code__ for function in
                         (calculate_fixed_replay, calculate_fixed_report, fixed_statistic_distribution,
                          actual_step_probabilities, signed_successes)}
            calls = []

            def profile(frame, event, arg):
                if event == 'call' and frame.f_code in monitored:
                    calls.append(frame.f_code.co_name)

            previous = sys.getprofile()
            sys.setprofile(profile)
            try:
                first = archive.read_report(original.id)
                second = archive.read_report(original.id)
                first.distribution.clear()
                third = archive.read_report(original.id)
            finally:
                sys.setprofile(previous)
            self.assertEqual(calls, [])
            self.assertEqual(second, original)
            self.assertEqual(third, original)
            with self.assertRaises(FrozenInstanceError):
                third.tail_mass = F(1)

    def test_reinitialize(self):
        with TrialArchive.open(self.path) as archive:
            for _ in range(2):
                initialize_schema(archive.connection)
            self.assertEqual(archive.connection.execute('SELECT count(*) FROM design_revisions').fetchone(), (0,))
            design, trial, replay, report = self._original(archive)
            before = archive.connection.total_changes
            initialize_schema(archive.connection)
            self.assertEqual(archive.connection.total_changes, before)
            self.assertEqual(archive.read_binding(replay.binding_id).design, design)
            self.assertEqual(archive.read_trial(trial.key), trial)
            self.assertEqual(archive.read_report(report.id), report)
            archive.connection.execute('PRAGMA user_version = 99')
            with self.assertRaisesRegex(ValueError, 'version 99'):
                initialize_schema(archive.connection)
            self.assertEqual(archive.connection.execute('PRAGMA user_version').fetchone(), (99,))
            self.assertEqual(archive.read_report(report.id), report)
        with self.assertRaisesRegex(ValueError, 'version 99'):
            TrialArchive.open(self.path)

    def test_export_integrity(self):
        with TrialArchive.open(self.path) as archive:
            _, _, _, report = self._original(archive)
            original = archive.export_report(report.id)
        self.assertEqual(verify_delivery_bundle(original).tail_mass, F(1, 8))
        no_replay = deepcopy(original)
        del no_replay['replay']
        wrong_response = deepcopy(original)
        wrong_response['trial']['records'][0]['response'] = 0
        for bad in (no_replay, wrong_response):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                verify_delivery_bundle(bad)

    def test_offline_recompute(self):
        with TrialArchive.open(self.path) as archive:
            _, _, replay, report = self._original(archive)
            original = load_json(canonical_json(archive.export_report(report.id)))
        result = verify_delivery_bundle(original)
        self.assertEqual(result.path_probability, F(1, 16))
        self.assertEqual(result.step_probabilities, replay.step_probabilities)
        self.assertEqual(result.observed_statistic, 4)
        self.assertEqual(result.distribution, {-4: F(1, 16), -2: F(1, 4), 0: F(3, 8), 2: F(1, 4), 4: F(1, 16)})
        self.assertEqual(result.tail_mass, F(1, 8))
        altered = deepcopy(original)
        altered['report']['distribution'] = [[-4, ['1', '8']], [0, ['3', '4']], [4, ['1', '8']]]
        altered['report']['tail_mass'] = ['1', '4']
        with self.assertRaisesRegex(ValueError, 'recomputed distribution differs'):
            verify_delivery_bundle(altered)

    def test_parent_chain(self):
        with TrialArchive.open(self.path) as archive:
            design, _, _, report = self._original(archive)
            corrected = archive.save_trial('day', design, records('AAAA', (1, 1, 1, 0)))
            _, new_report = archive.analyze_fixed(corrected)
            original = archive.export_report(report.id)
            newer = archive.export_report(new_report.id)
        for part in ('trial', 'replay', 'binding'):
            crossed = deepcopy(original)
            crossed[part] = newer[part]
            with self.subTest(part=part), self.assertRaises(ValueError):
                verify_delivery_bundle(crossed)
        incomplete = deepcopy(original)
        del incomplete['replay']
        changed = deepcopy(original)
        changed['trial']['records'][2]['response'] = 0
        for bad in (incomplete, changed):
            with self.assertRaises(ValueError):
                verify_delivery_bundle(bad)
        self.assertEqual(verify_delivery_bundle(original).report_id, report.id)

    def test_fraction_roundtrip(self):
        p = F(1, 10**12)
        expected = {-2: (1 - p)**2, 0: 2 * p * (1 - p), 2: F(1, 10**24)}
        with TrialArchive.open(self.path) as archive:
            design = archive.save_design('tiny', [p, p])
            revision = archive.save_trial('day', design, records('AA', (1, 1)))
            replay, report = archive.analyze_fixed(revision)
        with TrialArchive.open(self.path) as archive:
            self.assertEqual(archive.read_replay(replay.id).path_probability, F(1, 10**24))
            self.assertEqual(archive.read_report(report.id).distribution, expected)
            bundle = archive.export_report(report.id)
        self.assertEqual(bundle['replay']['path_probability'], encode_fraction(F(1, 10**24)))
        result = verify_delivery_bundle(load_json(canonical_json(bundle)))
        self.assertEqual(result.path_probability, F(1, 10**24))
        self.assertEqual(result.distribution, expected)
        self.assertEqual(result.tail_mass, expected[-2] + expected[2])
        for invalid in (['1', '0'], [1, '2'], ['2', '4'], '1/2'):
            bad = deepcopy(bundle)
            bad['replay']['path_probability'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                verify_delivery_bundle(bad)

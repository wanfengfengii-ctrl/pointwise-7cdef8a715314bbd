import unittest
from contextlib import redirect_stderr, redirect_stdout
from fractions import Fraction as F
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from trial.archive import TrialArchive, main
from trial.codec import decode_fraction, encode_fraction, load_json
from trial.path_probability import actual_step_probabilities
from trial.schedule import FixedSchedule
from trial.statistic import signed_successes
from tests.test_preparation import records


EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'day.json'


class TestContract(unittest.TestCase):
    def test_eighteen_steps_and_strict_lengths(self):
        with TrialArchive.open(':memory:') as archive:
            schedule = archive.save_design('eighteen', [F(1, 2)] * 18)
            trial = archive.save_trial('day', schedule, records('A' * 18, (1,) * 18))
            replay, report = archive.analyze_fixed(trial)
            self.assertEqual(replay.path_probability, F(1, 2**18))
            self.assertEqual(report.observed_statistic, 18)
            self.assertEqual(report.tail_mass, F(2, 2**18))
        with self.assertRaises(ValueError):
            signed_successes('AA', [1])
        with self.assertRaises(ValueError):
            actual_step_probabilities(FixedSchedule((F(1, 2),)), 'AA')
        with self.assertRaises(ValueError):
            schedule.schedule.probability_at(True)

    def test_codec_strictness_and_large_text(self):
        big = F(-1, 10**4500 + 1)
        encoded = encode_fraction(big)
        self.assertEqual(encoded[0], '-1')
        self.assertEqual(len(encoded[1]), 4501)
        self.assertEqual(decode_fraction(encoded), big)
        for text in ('{"response":0,"response":1}', '{"p": NaN}', '{"p": Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                load_json(text)
        for pair in (['+1', '2'], ['-0', '1'], ['1', '02'], ['1', '-2'], [True, '1']):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                decode_fraction(pair)

    def test_read_detects_corrupt_report(self):
        with TrialArchive.open(':memory:') as archive:
            design = archive.save_design('pair', [F(1, 2)] * 2)
            trial = archive.save_trial('day', design, records('AA', (1, 1)))
            _, report = archive.analyze_fixed(trial)
            archive.connection.execute('UPDATE reports SET tail_mass = ? WHERE id = ?', ('["1","4"]', report.id))
            with self.assertRaisesRegex(ValueError, 'tail mass differs'):
                archive.read_report(report.id)
            with self.assertRaises(KeyError):
                archive.read_report(9999)

    def _invoke(self, *args, status=0):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            actual_status = main(list(map(str, args)))
        self.assertEqual(actual_status, status, errors.getvalue())
        return output.getvalue(), errors.getvalue()

    def test_cli_roundtrip(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'test.sqlite'
            bundle = Path(directory) / 'bundle.json'
            output, _ = self._invoke('init', database)
            self.assertEqual(load_json(output), {'schema_version': 1})
            result, _ = self._invoke('analyze', database, EXAMPLE)
            result = load_json(result)
            self.assertEqual(result['path_probability'], ['1', '16'])
            report_id = result['report']['id']
            self._invoke('init', database)
            output, _ = self._invoke('read', database, report_id)
            self.assertEqual(load_json(output), result['report'])
            output, _ = self._invoke('export', database, report_id)
            bundle.write_text(output, encoding='utf-8')
            output, _ = self._invoke('verify', bundle)
            self.assertEqual(load_json(output), {'report_id': report_id, 'path_probability': ['1', '16'],
                                                 'observed_statistic': 4, 'tail_mass': ['1', '8']})
            output, error = self._invoke('read', database, 9999, status=1)
            self.assertEqual(output, '')
            self.assertIn('unknown report', error)

    def test_cli_demo(self):
        output, errors = self._invoke('demo', EXAMPLE)
        self.assertEqual(errors, '')
        prefix = 'POINTWISE_SCENARIO '
        self.assertTrue(output.startswith(prefix))
        marker = load_json(output[len(prefix):])
        self.assertEqual(marker['case_id'], 'v4')
        self.assertEqual(marker['actual'], {'path': ['1', '16'], 'statistic': 4, 'tail': ['1', '8']})
        self.assertEqual(marker['downstream_actual'], {'old_tail': ['1', '8'], 'new_statistic': 3,
                                                       'new_tail': ['1', '4'], 'new_path': ['1', '16'],
                                                       'verified_tail': ['1', '8']})

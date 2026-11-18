import argparse
import sqlite3
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from .adaptive_service import AdaptiveService
from .adaptive_store import AdaptiveDesignStore, AdaptiveReplayStore, AdaptiveReportStore
from .analysis_input import fixed_input_from_binding
from .bindings import BindingStore
from .codec import canonical_json, decode_fraction, encode_fraction, load_json, require_fields
from .delivery import build_delivery_bundle, report_value, validate_parent_chain
from .design import DesignService
from .design_store import DesignStore
from .design_validation import validate_design_id, validate_identity
from .inference import InferenceService, calculate_fixed_report
from .observation_store import ObservationStore
from .observations import ObservationService
from .publication import Publication
from .reconciliation import verify_delivery_bundle
from .record_validation import validate_records
from .replay import ReplayService, calculate_fixed_replay
from .replay_store import ReplayStore
from .report_store import ReportStore
from .revisions import TrialRevision
from .schedule import FixedDesignRevision, FixedSchedule
from .schema import initialize_schema


class TrialArchive:
    def __init__(self, connection):
        initialize_schema(connection)
        self.connection = connection
        self.publication = Publication(connection)
        self._designs = DesignStore(connection)
        self._observations = ObservationStore(connection)
        self._bindings = BindingStore(connection, self._designs, self._observations)
        self._replays = ReplayStore(connection)
        self._reports = ReportStore(connection, self.publication)
        self._adaptive_designs = AdaptiveDesignStore(connection)
        self._adaptive_replays = AdaptiveReplayStore(connection)
        self._adaptive_reports = AdaptiveReportStore(connection, self.publication)
        self.design = DesignService(self._designs, self.publication)
        self.observations = ObservationService(self._observations, self._designs, self.publication)
        self.replay = ReplayService(self._bindings, self._replays, self.publication)
        self.inference = InferenceService(self._bindings, self._replays, self._reports, self.publication)
        self.adaptive = AdaptiveService(self._adaptive_designs, self._adaptive_replays,
                                        self._adaptive_reports, self.publication)

    @classmethod
    def open(cls, database):
        connection = sqlite3.connect(database, isolation_level=None)
        try:
            return cls(connection)
        except BaseException:
            connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self.connection.close()

    def save_design(self, id, probabilities):
        return self.design.save_design(id, probabilities)

    def save_trial(self, id, design_revision, records):
        return self.observations.save_trial(id, design_revision, records)

    def read_design(self, design_revision):
        key = design_revision.key if isinstance(design_revision, FixedDesignRevision) else design_revision
        return self._designs.get_revision(key)

    def read_trial(self, trial_revision):
        key = trial_revision.key if isinstance(trial_revision, TrialRevision) else trial_revision
        return self._observations.get_revision(key)

    def replay_fixed(self, trial_revision):
        return self.replay.replay_fixed(trial_revision)

    def test_fixed(self, replay_id):
        return self.inference.test_fixed(replay_id)

    def analyze_fixed(self, trial_revision):
        binding = self._bindings.prepare_binding(trial_revision)
        replay_computation = calculate_fixed_replay(binding)
        analysis_input = fixed_input_from_binding(binding, replay_computation)
        report_computation = calculate_fixed_report(analysis_input)
        with self.publication.transaction():
            saved_binding = self._bindings.insert_binding(binding)
            replay = self._replays.insert_replay(saved_binding, replay_computation)
            report = self._reports.insert_report(replay.id, report_computation)
        return replay, report

    def read_binding(self, binding_id):
        return self._bindings.get_binding(binding_id)

    def read_replay(self, replay_id):
        replay = self._replays.get_replay(replay_id)
        try:
            binding = self._bindings.get_binding(replay.binding_id)
        except KeyError as exc:
            raise ValueError('replay is missing its binding') from exc
        if len(replay.step_probabilities) != len(binding.trial.records):
            raise ValueError('stored replay is incomplete for its bound trial')
        return replay

    def _read_evidence(self, report_id):
        report = self._reports.get_report(report_id)
        try:
            replay = self._replays.get_replay(report.replay_id)
            binding = self._bindings.get_binding(replay.binding_id)
        except KeyError as exc:
            raise ValueError('report has a missing parent') from exc
        validate_parent_chain(binding, replay, report)
        return binding, replay, report

    def read_report(self, report_id):
        return self._read_evidence(report_id)[2]

    def export_report(self, report_id):
        return build_delivery_bundle(*self._read_evidence(report_id))

    def save_adaptive(self, initial_a, initial_b, horizon, min_n, boundary):
        return self.adaptive.save_adaptive(initial_a, initial_b, horizon, min_n, boundary)

    def replay_adaptive(self, design_id, responses, assignments):
        return self.adaptive.replay_adaptive(design_id, responses, assignments)

    def test_adaptive(self, replay_id):
        return self.adaptive.test_adaptive(replay_id)

    def read_adaptive_replay(self, replay_id):
        return self.adaptive.read_adaptive_replay(replay_id)

    def read_adaptive_report(self, report_id):
        return self.adaptive.read_adaptive_report(report_id)


def _read_day(path):
    day = require_fields(load_json(Path(path).read_text(encoding='utf-8')),
                         'design_id', 'trial_id', 'probabilities', 'records')
    design_id = validate_design_id(day['design_id'])
    trial_id = validate_identity(day['trial_id'], 'trial ID')
    if type(day['probabilities']) is not list or type(day['records']) is not list:
        raise ValueError('day probabilities and records must be arrays')
    schedule = FixedSchedule(tuple(decode_fraction(value) for value in day['probabilities']))
    records = validate_records(day['records'], len(schedule))
    return design_id, trial_id, schedule, records


def _register_day(archive, day):
    design_id, trial_id, schedule, records = day
    design = archive.save_design(design_id, schedule.probabilities)
    return archive.save_trial(trial_id, design, records)


def _demo(day):
    _, _, schedule, records = day
    if (schedule.probabilities != (Fraction(1, 2),) * 4
            or tuple((row.assignment, row.response) for row in records) != (('A', 1),) * 4):
        raise ValueError('demo expects the four-success fair example')
    with TemporaryDirectory(prefix='river-trial-') as directory:
        database = Path(directory) / 'demo.sqlite'
        with TrialArchive.open(database) as archive:
            original = _register_day(archive, day)
            replay, report = archive.analyze_fixed(original)
            revision = archive.save_trial(original.id, original.design_key,
                                          (*original.records[:-1], replace(original.records[-1], response=0)))
            corrected_replay, corrected_report = archive.analyze_fixed(revision)
        with TrialArchive.open(database) as archive:
            old_report = archive.read_report(report.id)
            new_report = archive.read_report(corrected_report.id)
            bundle = archive.export_report(report.id)
        verified = verify_delivery_bundle(bundle)
        expected = {'path': ['1', '16'], 'statistic': 4, 'tail': ['1', '8']}
        actual = {'path': encode_fraction(replay.path_probability), 'statistic': replay.statistic,
                  'tail': encode_fraction(report.tail_mass)}
        downstream_expected = {'old_tail': ['1', '8'], 'new_statistic': 3, 'new_tail': ['1', '4'],
                               'new_path': ['1', '16'], 'verified_tail': ['1', '8']}
        downstream_actual = {'old_tail': encode_fraction(old_report.tail_mass),
                             'new_statistic': new_report.observed_statistic,
                             'new_tail': encode_fraction(new_report.tail_mass),
                             'new_path': encode_fraction(corrected_replay.path_probability),
                             'verified_tail': encode_fraction(verified.tail_mass)}
        if actual != expected or downstream_actual != downstream_expected:
            raise ValueError('demo calculation disagrees with the fair-plan hand calculation')
        evidence = {'case_id': 'v4', 'input': {'design': bundle['design'], 'trial': bundle['trial'],
                                             'correction': {'position': 4, 'response': 0}},
                    'expected': expected, 'actual': actual, 'downstream_expected': downstream_expected,
                    'downstream_actual': downstream_actual,
                    'code_paths': ['trial/archive.py', 'trial/replay.py', 'trial/inference.py',
                                   'trial/bindings.py', 'trial/reconciliation.py'],
                    'oracle': 'Four fair draws give path 1/16. Either all-success arm extreme has mass 2/2^4, or 2/2^3 after the correction.'}
        print('POINTWISE_SCENARIO ' + canonical_json(evidence))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fixed-design batch trial archive')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='initialize or check an archive').add_argument('database')
    analyze = commands.add_parser('analyze', help='register and analyze a complete day')
    analyze.add_argument('database')
    analyze.add_argument('input')
    for command in ('read', 'export'):
        subcommand = commands.add_parser(command)
        subcommand.add_argument('database')
        subcommand.add_argument('report_id', type=int)
    commands.add_parser('verify', help='recompute a self-contained report').add_argument('bundle')
    commands.add_parser('demo', help='run and reconcile the fair-plan example').add_argument('input')
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo':
            _demo(_read_day(args.input))
            return 0
        if args.command == 'verify':
            bundle = load_json(Path(args.bundle).read_text(encoding='utf-8'))
            result = verify_delivery_bundle(bundle)
            output = {'report_id': result.report_id, 'path_probability': encode_fraction(result.path_probability),
                      'observed_statistic': result.observed_statistic, 'tail_mass': encode_fraction(result.tail_mass)}
        else:
            day = _read_day(args.input) if args.command == 'analyze' else None
            with TrialArchive.open(args.database) as archive:
                if args.command == 'init':
                    output = {'schema_version': archive.connection.execute('PRAGMA user_version').fetchone()[0]}
                elif args.command == 'analyze':
                    replay, report = archive.analyze_fixed(_register_day(archive, day))
                    output = {'report': report_value(report), 'path_probability': encode_fraction(replay.path_probability)}
                elif args.command == 'read':
                    output = report_value(archive.read_report(args.report_id))
                else:
                    output = archive.export_report(args.report_id)
        print(canonical_json(output))
        return 0
    except (KeyError, ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f'trial archive: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

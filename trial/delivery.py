from .bindings import FrozenBinding, parse_key, parse_snapshot, snapshot_value, validate_binding
from .codec import decode_fraction, encode_fraction, require_fields
from .replay_store import FixedReplay, validate_replay_values
from .report_store import FixedReport, validate_report_values
from .revisions import positive_id


DELIVERY_FORMAT_VERSION = 1


def validate_parent_chain(binding, replay, report):
    validate_binding(binding)
    if binding.id != replay.binding_id or replay.design_key != binding.design.key or replay.trial_key != binding.trial.key:
        raise ValueError('replay parent keys differ from the frozen design and trial')
    if report.replay_id != replay.id or report.observed_statistic != replay.statistic:
        raise ValueError('report does not refer to its observed replay')
    if len(replay.step_probabilities) != len(binding.trial.records):
        raise ValueError('replay steps do not cover the complete frozen records')
    successes = sum(row.response for row in binding.trial.records)
    if any(abs(score) > successes or (score - successes) % 2 for score in report.distribution):
        raise ValueError('report support conflicts with the frozen success count')


def report_value(report):
    return {
        'id': report.id,
        'replay_id': report.replay_id,
        'observed_statistic': report.observed_statistic,
        'distribution': [[score, encode_fraction(mass)] for score, mass in sorted(report.distribution.items())],
        'tail_mass': encode_fraction(report.tail_mass),
    }


def build_delivery_bundle(binding, replay, report):
    validate_parent_chain(binding, replay, report)
    return {
        'version': DELIVERY_FORMAT_VERSION,
        **snapshot_value(binding.design, binding.trial),
        'binding': {
            'id': binding.id, 'fingerprint': binding.fingerprint,
            'design_key': list(binding.design.key), 'trial_key': list(binding.trial.key),
        },
        'replay': {
            'id': replay.id, 'binding_id': replay.binding_id,
            'design_key': list(replay.design_key), 'trial_key': list(replay.trial_key),
            'step_probabilities': [encode_fraction(p) for p in replay.step_probabilities],
            'path_probability': encode_fraction(replay.path_probability), 'statistic': replay.statistic,
        },
        'report': report_value(report),
    }


def _parse_replay(raw):
    require_fields(raw, 'id', 'binding_id', 'design_key', 'trial_key', 'step_probabilities', 'path_probability', 'statistic')
    if type(raw['step_probabilities']) is not list:
        raise ValueError('replay steps must be an array')
    replay = FixedReplay(
        positive_id(raw['id'], 'replay ID'), positive_id(raw['binding_id'], 'binding ID'),
        parse_key(raw['design_key'], 'replay design'), parse_key(raw['trial_key'], 'replay trial'),
        tuple(decode_fraction(p) for p in raw['step_probabilities']),
        decode_fraction(raw['path_probability']), raw['statistic'],
    )
    validate_replay_values(replay)
    return replay


def _parse_report(raw):
    require_fields(raw, 'id', 'replay_id', 'observed_statistic', 'distribution', 'tail_mass')
    if type(raw['distribution']) is not list:
        raise ValueError('distribution must be an array of score and mass pairs')
    distribution = {}
    for pair in raw['distribution']:
        if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not int:
            raise ValueError('invalid distribution entry')
        score, mass = pair
        if score in distribution:
            raise ValueError('duplicate distribution statistic')
        distribution[score] = decode_fraction(mass)
    report = FixedReport(positive_id(raw['id'], 'report ID'), positive_id(raw['replay_id'], 'replay ID'),
                         raw['observed_statistic'], distribution, decode_fraction(raw['tail_mass']))
    validate_report_values(report)
    return report


def parse_delivery_bundle(bundle):
    require_fields(bundle, 'version', 'design', 'trial', 'binding', 'replay', 'report')
    if type(bundle['version']) is not int or bundle['version'] != DELIVERY_FORMAT_VERSION:
        raise ValueError('unsupported delivery format version')
    design, trial = parse_snapshot({'design': bundle['design'], 'trial': bundle['trial']})
    raw = require_fields(bundle['binding'], 'id', 'fingerprint', 'design_key', 'trial_key')
    if parse_key(raw['design_key'], 'binding design') != design.key or parse_key(raw['trial_key'], 'binding trial') != trial.key:
        raise ValueError('delivery input keys differ from the binding')
    if type(raw['fingerprint']) is not str:
        raise ValueError('invalid binding fingerprint')
    binding = FrozenBinding(positive_id(raw['id'], 'binding ID'), design, trial, raw['fingerprint'])
    replay = _parse_replay(bundle['replay'])
    report = _parse_report(bundle['report'])
    validate_parent_chain(binding, replay, report)
    return binding, replay, report

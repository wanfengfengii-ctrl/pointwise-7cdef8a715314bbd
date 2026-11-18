from dataclasses import dataclass
from fractions import Fraction

from .adaptive import (
    MAX_ADAPTIVE_HORIZON,
    AdaptiveDesign,
    AdaptiveStep,
    replay_path_probability,
)
from .codec import fraction_from_text, fraction_text
from .publication import REPORT_DISTRIBUTION, REPORT_HEADER
from .revisions import positive_id
from .statistic import validate_response


class AdaptiveDesignStore:
    def __init__(self, connection):
        self.connection = connection

    def insert_design(self, design):
        cursor = self.connection.execute(
            'INSERT INTO adaptive_designs (initial_a, initial_b, horizon, min_n, boundary) '
            'VALUES (?, ?, ?, ?, ?)',
            (design.initial_a, design.initial_b, design.horizon, design.min_n, design.boundary),
        )
        return cursor.lastrowid

    def get_design(self, design_id):
        design_id = positive_id(design_id, 'adaptive design ID')
        row = self.connection.execute(
            'SELECT initial_a, initial_b, horizon, min_n, boundary FROM adaptive_designs WHERE id = ?',
            (design_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f'unknown adaptive design {design_id}')
        return AdaptiveDesign(*row)


@dataclass(frozen=True, slots=True)
class StoredAdaptiveReplay:
    id: int
    design_id: int
    steps: tuple
    path_probability: Fraction
    statistic: int


def validate_stored_replay(replay):
    steps = replay.steps
    if not 1 <= len(steps) <= MAX_ADAPTIVE_HORIZON:
        raise ValueError('invalid stored adaptive replay length')
    for expected, step in enumerate(steps, 1):
        if step.position != expected:
            raise ValueError('stored adaptive replay positions are incomplete')
        if type(step.assignment) is not str or step.assignment not in ('A', 'B'):
            raise ValueError('invalid stored adaptive assignment')
        validate_response(step.response)
        if (type(step.before) is not tuple or len(step.before) != 2
                or any(type(balls) is not int or balls < 1 for balls in step.before)):
            raise ValueError('invalid stored adaptive ball counts')
        if not isinstance(step.probability, Fraction) or not 0 < step.probability <= 1:
            raise ValueError('invalid stored adaptive step probability')
        if type(step.statistic) is not int or abs(step.statistic) > MAX_ADAPTIVE_HORIZON:
            raise ValueError('invalid stored adaptive statistic')
    if (not isinstance(replay.path_probability, Fraction)
            or replay.path_probability != replay_path_probability(steps)):
        raise ValueError('stored adaptive path mass differs from the stored step product')
    if type(replay.statistic) is not int or replay.statistic != steps[-1].statistic:
        raise ValueError('stored adaptive statistic differs from the final step')


class AdaptiveReplayStore:
    def __init__(self, connection):
        self.connection = connection

    def insert_replay(self, design_id, steps, path_probability, statistic):
        design_id = positive_id(design_id, 'adaptive design ID')
        stored = StoredAdaptiveReplay(None, design_id, steps, path_probability, statistic)
        validate_stored_replay(stored)
        cursor = self.connection.execute(
            'INSERT INTO adaptive_replays (design_id, length, path_probability, statistic) VALUES (?, ?, ?, ?)',
            (design_id, len(steps), fraction_text(path_probability), statistic),
        )
        replay_id = cursor.lastrowid
        self.connection.executemany(
            'INSERT INTO adaptive_replay_steps '
            '(replay_id, position, assignment, response, balls_a, balls_b, probability, statistic) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                (
                    replay_id, step.position, step.assignment, step.response,
                    step.before[0], step.before[1], fraction_text(step.probability), step.statistic,
                )
                for step in steps
            ),
        )
        return replay_id

    def get_replay(self, replay_id):
        replay_id = positive_id(replay_id, 'adaptive replay ID')
        row = self.connection.execute(
            'SELECT design_id, length, path_probability, statistic FROM adaptive_replays WHERE id = ?',
            (replay_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f'unknown adaptive replay {replay_id}')
        design_id, length, path_probability, statistic = row
        rows = self.connection.execute(
            'SELECT position, assignment, response, balls_a, balls_b, probability, statistic '
            'FROM adaptive_replay_steps WHERE replay_id = ? ORDER BY position',
            (replay_id,),
        ).fetchall()
        if len(rows) != length:
            raise ValueError('stored adaptive replay is incomplete for its length')
        steps = tuple(
            AdaptiveStep(position, assignment, response, (balls_a, balls_b),
                         fraction_from_text(probability), step_statistic)
            for position, assignment, response, balls_a, balls_b, probability, step_statistic in rows
        )
        stored = StoredAdaptiveReplay(
            replay_id, positive_id(design_id, 'adaptive design ID'), steps,
            fraction_from_text(path_probability), statistic,
        )
        validate_stored_replay(stored)
        return stored


def validate_report_masses(observed_statistic, stop_mass, joint_tail_mass, conditional_tail):
    if type(observed_statistic) is not int or abs(observed_statistic) > MAX_ADAPTIVE_HORIZON:
        raise ValueError('invalid adaptive report statistic')
    for label, mass in (('stop mass', stop_mass), ('joint tail mass', joint_tail_mass),
                        ('conditional tail', conditional_tail)):
        if not isinstance(mass, Fraction) or not 0 <= mass <= 1:
            raise ValueError(f'adaptive report {label} must be a Fraction in [0, 1]')
    if not 0 < joint_tail_mass <= stop_mass:
        raise ValueError('adaptive report masses are not nested')
    if conditional_tail * stop_mass != joint_tail_mass:
        raise ValueError('adaptive report conditional tail differs from the stored masses')


class AdaptiveReportStore:
    def __init__(self, connection, publication):
        self.connection = connection
        self.publication = publication

    def insert_report(self, replay_id, computation):
        replay_id = positive_id(replay_id, 'adaptive replay ID')
        validate_report_masses(computation.observed_statistic, computation.stop_mass,
                               computation.joint_tail_mass, computation.conditional_tail)
        cursor = self.connection.execute(
            'INSERT INTO adaptive_reports (replay_id, statistic, stop_mass, joint_tail_mass, conditional_tail) '
            'VALUES (?, ?, ?, ?, ?)',
            (replay_id, computation.observed_statistic, fraction_text(computation.stop_mass),
             fraction_text(computation.joint_tail_mass), fraction_text(computation.conditional_tail)),
        )
        self.publication.checkpoint(REPORT_HEADER)
        self.publication.checkpoint(REPORT_DISTRIBUTION)
        return cursor.lastrowid

    def get_report(self, report_id):
        report_id = positive_id(report_id, 'adaptive report ID')
        row = self.connection.execute(
            'SELECT r.replay_id, r.statistic, r.stop_mass, r.joint_tail_mass, r.conditional_tail, p.statistic '
            'FROM adaptive_reports AS r LEFT JOIN adaptive_replays AS p ON p.id = r.replay_id WHERE r.id = ?',
            (report_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f'unknown adaptive report {report_id}')
        replay_id, observed, stop, joint, conditional, parent_statistic = row
        if parent_statistic is None or observed != parent_statistic:
            raise ValueError('adaptive report statistic has no matching parent replay')
        stop_mass = fraction_from_text(stop)
        joint_tail_mass = fraction_from_text(joint)
        conditional_tail = fraction_from_text(conditional)
        validate_report_masses(observed, stop_mass, joint_tail_mass, conditional_tail)
        return {
            'id': report_id,
            'replay_id': positive_id(replay_id, 'adaptive replay ID'),
            'observed_statistic': observed,
            'stop_mass': stop_mass,
            'joint_tail_mass': joint_tail_mass,
            'conditional_tail': conditional_tail,
        }

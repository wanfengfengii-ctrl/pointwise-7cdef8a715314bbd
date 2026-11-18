from dataclasses import dataclass
from fractions import Fraction

from .codec import fraction_from_text, fraction_text
from .design_validation import MAX_FIXED_LENGTH
from .path_probability import multiply_path_probability
from .revisions import positive_id, revision_key


@dataclass(frozen=True, slots=True)
class FixedReplay:
    id: int
    binding_id: int
    design_key: tuple[str, int]
    trial_key: tuple[str, int]
    step_probabilities: tuple[Fraction, ...]
    path_probability: Fraction
    statistic: int


def validate_replay_values(replay):
    steps = replay.step_probabilities
    if not 1 <= len(steps) <= MAX_FIXED_LENGTH or any(
        not isinstance(probability, Fraction) or not 0 < probability <= 1 for probability in steps
    ):
        raise ValueError('invalid stored replay step probabilities')
    if type(replay.statistic) is not int or abs(replay.statistic) > len(steps):
        raise ValueError('invalid stored replay statistic')
    if not isinstance(replay.path_probability, Fraction) or replay.path_probability != multiply_path_probability(steps):
        raise ValueError('stored replay mass differs from the stored step product')


class ReplayStore:
    def __init__(self, connection):
        self.connection = connection

    def insert_replay(self, binding, computation):
        binding_id = positive_id(binding.id, 'binding ID')
        validate_replay_values(computation)
        cursor = self.connection.execute(
            'INSERT INTO replays (binding_id, path_probability, statistic) VALUES (?, ?, ?)',
            (binding_id, fraction_text(computation.path_probability), computation.statistic),
        )
        replay = FixedReplay(cursor.lastrowid, binding_id, binding.design.key, binding.trial.key,
                             computation.step_probabilities, computation.path_probability, computation.statistic)
        self.connection.executemany(
            'INSERT INTO replay_steps (replay_id, position, probability) VALUES (?, ?, ?)',
            ((replay.id, pos, fraction_text(p)) for pos, p in enumerate(replay.step_probabilities, 1)),
        )
        return replay

    def get_replay(self, replay_id):
        replay_id = positive_id(replay_id, 'replay ID')
        row = self.connection.execute(
            'SELECT r.binding_id, b.design_id, b.design_revision, b.trial_id, b.trial_revision, '
            'r.path_probability, r.statistic FROM replays AS r LEFT JOIN bindings AS b ON b.id = r.binding_id '
            'WHERE r.id = ?', (replay_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f'unknown replay {replay_id}')
        binding_id, design_id, design_revision, trial_id, trial_revision, probability, statistic = row
        steps = self.connection.execute(
            'SELECT position, probability FROM replay_steps WHERE replay_id = ? ORDER BY position', (replay_id,)
        ).fetchall()
        if any(position != expected for expected, (position, _) in enumerate(steps, 1)):
            raise ValueError('stored replay step positions are incomplete')
        replay = FixedReplay(
            replay_id, positive_id(binding_id, 'binding ID'),
            revision_key((design_id, design_revision), 'replay design'),
            revision_key((trial_id, trial_revision), 'replay trial'),
            tuple(fraction_from_text(value) for _, value in steps), fraction_from_text(probability), statistic,
        )
        validate_replay_values(replay)
        return replay

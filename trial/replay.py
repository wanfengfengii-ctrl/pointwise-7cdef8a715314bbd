from dataclasses import dataclass
from fractions import Fraction

from .bindings import validate_binding
from .path_probability import actual_step_probabilities, multiply_path_probability
from .statistic import signed_successes


@dataclass(frozen=True, slots=True)
class ReplayComputation:
    step_probabilities: tuple[Fraction, ...]
    path_probability: Fraction
    statistic: int


def calculate_fixed_replay(binding):
    validate_binding(binding)
    assignments = tuple(row.assignment for row in binding.trial.records)
    responses = tuple(row.response for row in binding.trial.records)
    steps = actual_step_probabilities(binding.design.schedule, assignments)
    for position, probability in enumerate(steps, 1):
        if probability == 0:
            raise ValueError(f'actual assignment has zero probability at position {position}')
    return ReplayComputation(steps, multiply_path_probability(steps), signed_successes(assignments, responses))


class ReplayService:
    def __init__(self, bindings, store, publication):
        self.bindings = bindings
        self.store = store
        self.publication = publication

    def replay_fixed(self, trial_revision):
        binding = self.bindings.prepare_binding(trial_revision)
        computation = calculate_fixed_replay(binding)
        with self.publication.transaction():
            saved = self.bindings.insert_binding(binding)
            return self.store.insert_replay(saved, computation)

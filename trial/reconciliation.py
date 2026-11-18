from dataclasses import dataclass
from fractions import Fraction

from .delivery import parse_delivery_bundle
from .distribution import fixed_statistic_distribution
from .path_probability import actual_step_probabilities, multiply_path_probability
from .statistic import signed_successes
from .tails import inclusive_two_sided_mass


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    report_id: int
    step_probabilities: tuple[Fraction, ...]
    path_probability: Fraction
    observed_statistic: int
    distribution: dict[int, Fraction]
    tail_mass: Fraction


def verify_delivery_bundle(bundle):
    binding, replay, report = parse_delivery_bundle(bundle)
    schedule = binding.design.schedule
    assignments = tuple(row.assignment for row in binding.trial.records)
    responses = tuple(row.response for row in binding.trial.records)
    steps = actual_step_probabilities(schedule, assignments)
    probability = multiply_path_probability(steps)
    if probability == 0 or (steps, probability) != (replay.step_probabilities, replay.path_probability):
        raise ValueError('recomputed path probabilities differ from the delivered replay')
    observed = signed_successes(assignments, responses)
    if observed != replay.statistic or observed != report.observed_statistic:
        raise ValueError('recomputed observed statistic differs from the delivery')
    distribution = fixed_statistic_distribution(schedule.probabilities, responses)
    if distribution != report.distribution:
        raise ValueError('recomputed distribution differs from the delivered report')
    tail = inclusive_two_sided_mass(distribution, observed)
    if tail != report.tail_mass:
        raise ValueError('recomputed tail mass differs from the delivered report')
    return ReconciliationResult(report.id, steps, probability, observed, distribution, tail)

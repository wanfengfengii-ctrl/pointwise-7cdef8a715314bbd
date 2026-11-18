from dataclasses import dataclass
from fractions import Fraction

from .analysis_input import load_fixed_analysis_input
from .distribution import fixed_statistic_distribution
from .tails import inclusive_two_sided_mass


@dataclass(frozen=True, slots=True)
class ReportComputation:
    observed_statistic: int
    distribution: dict[int, Fraction]
    tail_mass: Fraction


def calculate_fixed_report(analysis_input):
    distribution = fixed_statistic_distribution(analysis_input.probabilities, analysis_input.responses)
    observed = analysis_input.observed_statistic
    if type(observed) is not int or observed not in distribution:
        raise ValueError('observed statistic is outside the fixed-design support')
    return ReportComputation(observed, distribution, inclusive_two_sided_mass(distribution, observed))


class InferenceService:
    def __init__(self, bindings, replays, reports, publication):
        self.bindings = bindings
        self.replays = replays
        self.reports = reports
        self.publication = publication

    def test_fixed(self, replay_id):
        analysis_input = load_fixed_analysis_input(self.bindings, self.replays, replay_id)
        computation = calculate_fixed_report(analysis_input)
        with self.publication.transaction():
            return self.reports.insert_report(replay_id, computation)

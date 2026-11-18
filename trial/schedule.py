from dataclasses import dataclass
from fractions import Fraction

from .design_validation import normalize_probabilities


@dataclass(frozen=True, slots=True)
class FixedSchedule:
    probabilities: tuple[Fraction, ...]

    def __post_init__(self):
        object.__setattr__(self, 'probabilities', normalize_probabilities(self.probabilities))

    def __len__(self):
        return len(self.probabilities)

    def probability_at(self, position):
        if type(position) is not int or not 1 <= position <= len(self):
            raise ValueError('position is outside the fixed schedule')
        return self.probabilities[position - 1]

    def assignment_probability(self, position, assignment):
        if type(assignment) is not str or assignment not in ('A', 'B'):
            raise ValueError('assignment must be A or B')
        probability = self.probability_at(position)
        return probability if assignment == 'A' else 1 - probability


@dataclass(frozen=True, slots=True)
class FixedDesignRevision:
    id: str
    revision: int
    schedule: FixedSchedule

    @property
    def key(self):
        return self.id, self.revision

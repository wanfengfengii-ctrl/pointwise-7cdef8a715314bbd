from fractions import Fraction
from math import prod


def actual_step_probabilities(schedule, assignments):
    if len(schedule) != len(assignments):
        raise ValueError('assignment length does not match the fixed schedule')
    return tuple(schedule.assignment_probability(position, assignment)
                 for position, assignment in enumerate(assignments, 1))


def multiply_path_probability(probabilities):
    return prod(probabilities, start=Fraction(1))

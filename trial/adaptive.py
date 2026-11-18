from dataclasses import dataclass
from fractions import Fraction

from .path_probability import multiply_path_probability
from .statistic import validate_response


MIN_ADAPTIVE_BATCHES = 2
MAX_ADAPTIVE_HORIZON = 18


def _integer(value, label):
    if type(value) is not int:
        raise ValueError(f'{label} must be a non-boolean integer')
    return value


@dataclass(frozen=True, slots=True)
class AdaptiveDesign:
    initial_a: int
    initial_b: int
    horizon: int
    min_n: int
    boundary: int

    def __post_init__(self):
        initial_a = _integer(self.initial_a, 'initial A balls')
        initial_b = _integer(self.initial_b, 'initial B balls')
        horizon = _integer(self.horizon, 'horizon')
        min_n = _integer(self.min_n, 'minimum batches')
        boundary = _integer(self.boundary, 'boundary')
        if initial_a < 1 or initial_b < 1:
            raise ValueError('initial ball counts must be positive integers')
        if boundary < 1:
            raise ValueError('boundary must be a positive integer')
        if not MIN_ADAPTIVE_BATCHES <= min_n <= horizon <= MAX_ADAPTIVE_HORIZON:
            raise ValueError(
                f'require {MIN_ADAPTIVE_BATCHES} <= min_n <= horizon <= {MAX_ADAPTIVE_HORIZON}'
            )


def design_value(design):
    return {
        'initial_a': design.initial_a,
        'initial_b': design.initial_b,
        'horizon': design.horizon,
        'min_n': design.min_n,
        'boundary': design.boundary,
    }


def normalize_responses(responses):
    if not isinstance(responses, (list, tuple)):
        raise ValueError('responses must be a list or tuple in arrival order')
    return tuple(validate_response(response) for response in responses)


def normalize_assignments(assignments):
    if type(assignments) is str:
        arms = tuple(assignments)
    elif isinstance(assignments, (list, tuple)):
        arms = tuple(assignments)
    else:
        raise ValueError('assignments must be a string or a list or tuple of arms')
    for arm in arms:
        if type(arm) is not str or arm not in ('A', 'B'):
            raise ValueError('assignment must be A or B')
    return arms


def _advance(balls_a, balls_b, statistic, assignment, response):
    if response == 1:
        if assignment == 'A':
            return balls_a + 1, balls_b, statistic + 1
        return balls_a, balls_b + 1, statistic - 1
    if assignment == 'A':
        return balls_a, balls_b + 1, statistic
    return balls_a + 1, balls_b, statistic


@dataclass(frozen=True, slots=True)
class AdaptiveStep:
    position: int
    assignment: str
    response: int
    before: tuple
    probability: Fraction
    statistic: int


def walk_adaptive(design, responses, assignments):
    if len(responses) != len(assignments):
        raise ValueError('responses and assignments differ in length')
    if len(responses) > design.horizon:
        raise ValueError('the record continues past the design horizon')
    steps = []
    balls_a, balls_b, statistic = design.initial_a, design.initial_b, 0
    stop_position = None
    for position, (response, assignment) in enumerate(zip(responses, assignments), 1):
        before = (balls_a, balls_b)
        probability = Fraction(balls_a if assignment == 'A' else balls_b, balls_a + balls_b)
        balls_a, balls_b, statistic = _advance(balls_a, balls_b, statistic, assignment, response)
        steps.append(AdaptiveStep(position, assignment, response, before, probability, statistic))
        if stop_position is None and position >= design.min_n and abs(statistic) >= design.boundary:
            stop_position = position
    if stop_position is not None and stop_position < len(steps):
        raise ValueError('the record continues past the first stopping time')
    if stop_position is None and len(steps) < design.horizon:
        raise ValueError('the record ends before any stopping time')
    return tuple(steps)


def replay_path_probability(steps):
    return multiply_path_probability(tuple(step.probability for step in steps))


def conditional_stop_masses(design, responses, observed_statistic):
    n = len(responses)
    threshold = abs(observed_statistic)
    stop_mass = Fraction(0)
    joint_mass = Fraction(0)
    stack = [(0, design.initial_a, design.initial_b, 0, Fraction(1))]
    while stack:
        position, balls_a, balls_b, statistic, mass = stack.pop()
        response = responses[position]
        total = balls_a + balls_b
        for assignment in ('A', 'B'):
            probability = Fraction(balls_a if assignment == 'A' else balls_b, total)
            next_a, next_b, next_statistic = _advance(balls_a, balls_b, statistic, assignment, response)
            next_position = position + 1
            stopped = next_position >= design.min_n and abs(next_statistic) >= design.boundary
            child_mass = mass * probability
            if next_position == n:
                if stopped or next_position == design.horizon:
                    stop_mass += child_mass
                    if abs(next_statistic) >= threshold:
                        joint_mass += child_mass
            elif not stopped:
                stack.append((next_position, next_a, next_b, next_statistic, child_mass))
    return stop_mass, joint_mass


@dataclass(frozen=True, slots=True)
class AdaptiveReportComputation:
    observed_statistic: int
    stop_mass: Fraction
    joint_tail_mass: Fraction
    conditional_tail: Fraction


def calculate_adaptive_report(design, responses, observed_statistic):
    stop_mass, joint_mass = conditional_stop_masses(design, responses, observed_statistic)
    if stop_mass <= 0:
        raise ValueError('no counterfactual path first stops at the observed length')
    return AdaptiveReportComputation(observed_statistic, stop_mass, joint_mass, joint_mass / stop_mass)


def replay_value(replay_id, design_id, design, steps, path_probability, statistic):
    return {
        'id': replay_id,
        'design_id': design_id,
        'design': design_value(design),
        'responses': [step.response for step in steps],
        'assignments': [step.assignment for step in steps],
        'steps': [
            {
                'position': step.position,
                'before': [step.before[0], step.before[1]],
                'probability': step.probability,
                'statistic': step.statistic,
            }
            for step in steps
        ],
        'path_probability': path_probability,
        'statistic': statistic,
    }


def report_value(report_id, replay_id, computation):
    return {
        'id': report_id,
        'replay_id': replay_id,
        'observed_statistic': computation.observed_statistic,
        'stop_mass': computation.stop_mass,
        'joint_tail_mass': computation.joint_tail_mass,
        'conditional_tail': computation.conditional_tail,
    }

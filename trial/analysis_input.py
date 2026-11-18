from dataclasses import dataclass
from fractions import Fraction

from .bindings import validate_binding
from .path_probability import actual_step_probabilities, multiply_path_probability
from .replay_store import FixedReplay
from .statistic import signed_successes


@dataclass(frozen=True, slots=True)
class FixedAnalysisInput:
    probabilities: tuple[Fraction, ...]
    responses: tuple[int, ...]
    observed_statistic: int


def fixed_input_from_binding(binding, replay):
    validate_binding(binding)
    if isinstance(replay, FixedReplay) and (
        replay.binding_id != binding.id or replay.design_key != binding.design.key or replay.trial_key != binding.trial.key
    ):
        raise ValueError('replay refers to different frozen input')
    rows = binding.trial.records
    schedule = binding.design.schedule
    assignments = tuple(row.assignment for row in rows)
    responses = tuple(row.response for row in rows)
    steps = actual_step_probabilities(schedule, assignments)
    if 0 in steps or steps != replay.step_probabilities or multiply_path_probability(steps) != replay.path_probability:
        raise ValueError('replay probabilities differ from the fixed analysis input')
    observed = signed_successes(assignments, responses)
    if type(replay.statistic) is not int or observed != replay.statistic:
        raise ValueError('replay statistic differs from the fixed analysis input')
    return FixedAnalysisInput(schedule.probabilities, responses, observed)


def load_fixed_analysis_input(bindings, replays, replay_id):
    replay = replays.get_replay(replay_id)
    try:
        binding = bindings.get_binding(replay.binding_id)
    except KeyError as exc:
        raise ValueError('replay is missing its frozen binding') from exc
    return fixed_input_from_binding(binding, replay)

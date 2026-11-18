from collections import defaultdict
from fractions import Fraction

from .design_validation import normalize_probabilities
from .statistic import validate_response


def validate_distribution(distribution):
    if not distribution or any(
        type(score) is not int or not isinstance(mass, Fraction) or not 0 < mass <= 1
        for score, mass in distribution.items()
    ):
        raise ValueError('distribution requires integer scores with positive Fraction masses')
    if sum(distribution.values(), Fraction(0)) != 1:
        raise ValueError('distribution is not exactly normalized')


def fixed_statistic_distribution(probabilities, responses):
    probabilities = normalize_probabilities(probabilities)
    if len(probabilities) != len(responses):
        raise ValueError('response count does not match the fixed design')
    distribution = {0: Fraction(1)}
    for probability, response in zip(probabilities, responses, strict=True):
        response = validate_response(response)
        following = defaultdict(Fraction)
        for statistic, mass in distribution.items():
            if probability > 0:
                following[statistic + response] += mass * probability
            if probability < 1:
                following[statistic - response] += mass * (1 - probability)
        distribution = following
    ordered = dict(sorted(distribution.items()))
    validate_distribution(ordered)
    return ordered

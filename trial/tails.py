from fractions import Fraction


def inclusive_two_sided_mass(distribution, observed_statistic):
    threshold = abs(observed_statistic)
    return sum((mass for score, mass in distribution.items() if abs(score) >= threshold), Fraction(0))


def validate_tail_mass(distribution, observed_statistic, tail_mass):
    if not isinstance(tail_mass, Fraction) or not 0 <= tail_mass <= 1:
        raise ValueError('tail mass must be a Fraction in [0, 1]')
    if tail_mass != inclusive_two_sided_mass(distribution, observed_statistic):
        raise ValueError('tail mass differs from the stored distribution and observed statistic')

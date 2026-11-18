from collections.abc import Sequence
from fractions import Fraction
from numbers import Rational


MAX_FIXED_LENGTH = 18


def validate_identity(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f'{label} must be a nonblank string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{label} must be valid UTF-8 text') from exc
    return value


def validate_design_id(value):
    return validate_identity(value, 'design ID')


def normalize_probabilities(probabilities):
    if not isinstance(probabilities, Sequence) or isinstance(probabilities, (str, bytes, bytearray)):
        raise ValueError('probabilities must be an ordered sequence')
    values = tuple(probabilities)
    if not 1 <= len(values) <= MAX_FIXED_LENGTH:
        raise ValueError(f'fixed design length must be 1 to {MAX_FIXED_LENGTH}')
    result = []
    for position, value in enumerate(values, 1):
        if isinstance(value, bool) or not isinstance(value, Rational):
            raise ValueError(f'probability at position {position} must be rational')
        probability = Fraction(value)
        if not 0 <= probability <= 1:
            raise ValueError(f'probability at position {position} is outside [0, 1]')
        result.append(probability)
    return tuple(result)

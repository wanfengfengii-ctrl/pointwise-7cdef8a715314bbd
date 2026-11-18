import json
import re
from fractions import Fraction


_INTEGER_TEXT = re.compile(r'0|-?[1-9][0-9]*')
_CHUNK_BASE = 10**9


def _integer_text(value):
    try:
        return str(value)
    except ValueError:
        remaining = abs(value)
        chunks = []
        while remaining >= _CHUNK_BASE:
            remaining, chunk = divmod(remaining, _CHUNK_BASE)
            chunks.append(f'{chunk:09d}')
        sign = '-' if value < 0 else ''
        return sign + str(remaining) + ''.join(reversed(chunks))


def _parse_integer_text(value):
    if type(value) is not str or _INTEGER_TEXT.fullmatch(value) is None:
        raise ValueError('expected canonical decimal integer text')
    try:
        return int(value)
    except ValueError:
        negative = value.startswith('-')
        digits = value[1:] if negative else value
        result = 0
        for start in range(0, len(digits), 9):
            chunk = digits[start:start + 9]
            result = result * (10 ** len(chunk)) + int(chunk)
        return -result if negative else result


def encode_fraction(value):
    if not isinstance(value, Fraction):
        raise ValueError('expected Fraction')
    return [_integer_text(value.numerator), _integer_text(value.denominator)]


def decode_fraction(value):
    if type(value) is not list or len(value) != 2:
        raise ValueError('expected a pair of decimal strings for Fraction')
    numerator, denominator = map(_parse_integer_text, value)
    if denominator <= 0:
        raise ValueError('Fraction denominator must be positive')
    fraction = Fraction(numerator, denominator)
    if (fraction.numerator, fraction.denominator) != (numerator, denominator):
        raise ValueError('Fraction must be in lowest terms')
    return fraction


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'duplicate JSON key {key!r}')
        obj[key] = value
    return obj


def _reject_constant(value):
    raise ValueError(f'invalid JSON constant {value}')


def load_json(text):
    if type(text) is not str:
        raise ValueError('expected JSON text')
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def require_fields(value, *fields):
    if type(value) is not dict or value.keys() != set(fields):
        raise ValueError('expected fields: ' + ', '.join(fields))
    return value


def fraction_text(value):
    return canonical_json(encode_fraction(value))


def fraction_from_text(text):
    return decode_fraction(load_json(text))

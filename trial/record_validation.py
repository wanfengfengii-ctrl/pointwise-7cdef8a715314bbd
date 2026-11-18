from collections.abc import Mapping, Sequence

from .design_validation import MAX_FIXED_LENGTH, validate_identity
from .revisions import BatchRecord
from .statistic import validate_response


_FIELDS = ('batch_id', 'position', 'assignment', 'response')


def _record_values(raw):
    if isinstance(raw, BatchRecord):
        return raw.batch_id, raw.position, raw.assignment, raw.response
    if isinstance(raw, Mapping) and raw.keys() == set(_FIELDS):
        return tuple(raw[field] for field in _FIELDS)
    raise ValueError('batch record must specify batch_id, position, assignment and response')


def validate_records(records, length):
    if type(length) is not int or not 1 <= length <= MAX_FIXED_LENGTH:
        raise ValueError('invalid fixed record length')
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise ValueError('records must be an ordered sequence')
    records = tuple(records)
    if len(records) != length:
        raise ValueError('record count does not match the fixed design')
    result = []
    seen = set()
    for expected_position, raw in enumerate(records, 1):
        identity, position, assignment, response = _record_values(raw)
        validate_identity(identity, 'batch ID')
        if identity in seen:
            raise ValueError(f'duplicate batch ID {identity!r}')
        if type(position) is not int or position != expected_position:
            raise ValueError(f'expected arrival position {expected_position}')
        if type(assignment) is not str or assignment not in ('A', 'B'):
            raise ValueError('assignment must be A or B')
        result.append(BatchRecord(identity, position, assignment, validate_response(response)))
        seen.add(identity)
    return tuple(result)

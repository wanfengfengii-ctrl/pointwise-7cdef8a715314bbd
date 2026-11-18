from dataclasses import dataclass

from .design_validation import validate_identity


@dataclass(frozen=True, slots=True)
class BatchRecord:
    batch_id: str
    position: int
    assignment: str
    response: int


@dataclass(frozen=True, slots=True)
class TrialRevision:
    id: str
    revision: int
    design_key: tuple[str, int]
    records: tuple[BatchRecord, ...]

    @property
    def key(self):
        return self.id, self.revision


def positive_id(value, label):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError(f'{label} must be a positive 64-bit integer')
    return value


def revision_key(key, label):
    if type(key) is not tuple or len(key) != 2:
        raise ValueError(f'{label} must specify an (id, revision) key')
    identity, version = key
    return validate_identity(identity, f'{label} ID'), positive_id(version, f'{label} revision')

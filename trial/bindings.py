from dataclasses import asdict, dataclass, replace
from hashlib import sha256

from .codec import canonical_json, decode_fraction, encode_fraction, load_json, require_fields
from .record_validation import validate_records
from .revisions import TrialRevision, positive_id, revision_key
from .schedule import FixedDesignRevision, FixedSchedule


@dataclass(frozen=True, slots=True)
class FrozenBinding:
    id: int | None
    design: FixedDesignRevision
    trial: TrialRevision
    fingerprint: str


def snapshot_value(design, trial):
    return {
        'design': {
            'id': design.id,
            'revision': design.revision,
            'probabilities': [encode_fraction(p) for p in design.schedule.probabilities],
        },
        'trial': {
            'id': trial.id,
            'revision': trial.revision,
            'design_key': list(trial.design_key),
            'records': [asdict(row) for row in trial.records],
        },
    }


def parse_key(value, label):
    if type(value) is not list:
        raise ValueError(f'{label} must be an encoded revision key')
    return revision_key(tuple(value), label)


def parse_snapshot(value):
    require_fields(value, 'design', 'trial')
    design = require_fields(value['design'], 'id', 'revision', 'probabilities')
    trial = require_fields(value['trial'], 'id', 'revision', 'design_key', 'records')
    design_key = revision_key((design['id'], design['revision']), 'design')
    trial_key = revision_key((trial['id'], trial['revision']), 'trial')
    probabilities = design['probabilities']
    records = trial['records']
    if type(probabilities) is not list or type(records) is not list:
        raise ValueError('snapshot probabilities and records must be arrays')
    schedule = FixedSchedule(tuple(decode_fraction(item) for item in probabilities))
    rows = validate_records(records, len(schedule))
    return (
        FixedDesignRevision(*design_key, schedule),
        TrialRevision(*trial_key, parse_key(trial['design_key'], 'trial design'), rows),
    )


def _fingerprint(design, trial):
    snapshot = canonical_json(snapshot_value(design, trial))
    return sha256(snapshot.encode('utf-8')).hexdigest()


def validate_binding(binding):
    if binding.design.key != binding.trial.design_key:
        raise ValueError('frozen trial and design revisions differ')
    if len(binding.trial.records) != len(binding.design.schedule):
        raise ValueError('frozen trial length differs from its plan')
    if binding.fingerprint != _fingerprint(binding.design, binding.trial):
        raise ValueError('frozen input fingerprint differs')


class BindingStore:
    def __init__(self, connection, designs, observations):
        self.connection = connection
        self.designs = designs
        self.observations = observations

    def prepare_binding(self, trial_revision):
        key = trial_revision.key if isinstance(trial_revision, TrialRevision) else trial_revision
        trial = self.observations.get_revision(key)
        if isinstance(trial_revision, TrialRevision) and trial_revision != trial:
            raise ValueError('trial revision value differs from the stored revision')
        design = self.designs.get_revision(trial.design_key)
        return FrozenBinding(None, design, trial, _fingerprint(design, trial))

    def insert_binding(self, binding):
        if binding.id is not None:
            raise ValueError('binding already has an identity')
        validate_binding(binding)
        cursor = self.connection.execute(
            'INSERT INTO bindings (design_id, design_revision, trial_id, trial_revision, snapshot, fingerprint) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (*binding.design.key, *binding.trial.key,
             canonical_json(snapshot_value(binding.design, binding.trial)), binding.fingerprint),
        )
        return replace(binding, id=cursor.lastrowid)

    def get_binding(self, binding_id):
        binding_id = positive_id(binding_id, 'binding ID')
        row = self.connection.execute(
            'SELECT design_id, design_revision, trial_id, trial_revision, snapshot, fingerprint '
            'FROM bindings WHERE id = ?', (binding_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f'unknown binding {binding_id}')
        design_id, design_revision, trial_id, trial_revision, snapshot, fingerprint = row
        design, trial = parse_snapshot(load_json(snapshot))
        binding = FrozenBinding(binding_id, design, trial, fingerprint)
        validate_binding(binding)
        if design.key != (design_id, design_revision) or trial.key != (trial_id, trial_revision):
            raise ValueError('stored binding keys differ from frozen input')
        try:
            stored_design = self.designs.get_revision(design.key)
            stored_trial = self.observations.get_revision(trial.key)
        except KeyError as exc:
            raise ValueError('stored binding has a missing revision') from exc
        if design != stored_design or trial != stored_trial:
            raise ValueError('stored revisions differ from frozen input')
        return binding

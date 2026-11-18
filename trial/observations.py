from .design_validation import validate_identity
from .record_validation import validate_records
from .schedule import FixedDesignRevision


class ObservationService:
    def __init__(self, store, designs, publication):
        self.store = store
        self.designs = designs
        self.publication = publication

    def save_trial(self, id, design_revision, records):
        identity = validate_identity(id, 'trial ID')
        key = design_revision.key if isinstance(design_revision, FixedDesignRevision) else design_revision
        design = self.designs.get_revision(key)
        if isinstance(design_revision, FixedDesignRevision) and design_revision != design:
            raise ValueError('design revision value differs from the stored revision')
        batch = validate_records(records, len(design.schedule))
        with self.publication.transaction():
            return self.store.append_revision(identity, design.key, batch)

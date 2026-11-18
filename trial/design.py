from .design_validation import validate_design_id
from .schedule import FixedSchedule


class DesignService:
    def __init__(self, store, publication):
        self.store = store
        self.publication = publication

    def save_design(self, id, probabilities):
        identity = validate_design_id(id)
        schedule = FixedSchedule(probabilities)
        with self.publication.transaction():
            return self.store.append_revision(identity, schedule)

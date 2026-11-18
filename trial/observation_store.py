from .record_validation import validate_records
from .revisions import BatchRecord, TrialRevision, revision_key


class ObservationStore:
    def __init__(self, connection):
        self.connection = connection

    def append_revision(self, identity, design_key, records):
        previous, = self.connection.execute(
            'SELECT COALESCE(MAX(revision), 0) FROM trial_revisions WHERE trial_id = ?', (identity,)
        ).fetchone()
        revision = TrialRevision(identity, previous + 1, design_key, records)
        self.connection.execute(
            'INSERT INTO trial_revisions (trial_id, revision, design_id, design_revision) VALUES (?, ?, ?, ?)',
            (*revision.key, *design_key),
        )
        self.connection.executemany(
            'INSERT INTO batch_records (trial_id, revision, batch_id, position, assignment, response) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            ((*revision.key, row.batch_id, row.position, row.assignment, row.response) for row in records),
        )
        return revision

    def get_revision(self, key):
        key = revision_key(key, 'trial')
        header = self.connection.execute(
            'SELECT t.design_id, t.design_revision, d.length FROM trial_revisions AS t '
            'LEFT JOIN design_revisions AS d ON (d.design_id, d.revision) = (t.design_id, t.design_revision) '
            'WHERE t.trial_id = ? AND t.revision = ?', key
        ).fetchone()
        if header is None:
            raise KeyError(f'unknown trial revision {key!r}')
        design_id, design_revision, length = header
        if length is None:
            raise ValueError('stored trial refers to a missing design revision')
        design_key = revision_key((design_id, design_revision), 'design')
        rows = self.connection.execute(
            'SELECT batch_id, position, assignment, response FROM batch_records '
            'WHERE trial_id = ? AND revision = ? ORDER BY position', key
        ).fetchall()
        records = validate_records(tuple(BatchRecord(*row) for row in rows), length)
        return TrialRevision(*key, design_key, records)

from .codec import fraction_from_text, fraction_text
from .revisions import revision_key
from .schedule import FixedDesignRevision, FixedSchedule


class DesignStore:
    def __init__(self, connection):
        self.connection = connection

    def append_revision(self, identity, schedule):
        previous, = self.connection.execute(
            'SELECT COALESCE(MAX(revision), 0) FROM design_revisions WHERE design_id = ?', (identity,)
        ).fetchone()
        design = FixedDesignRevision(identity, previous + 1, schedule)
        self.connection.execute(
            'INSERT INTO design_revisions (design_id, revision, length) VALUES (?, ?, ?)',
            (*design.key, len(schedule)),
        )
        self.connection.executemany(
            'INSERT INTO design_probabilities (design_id, revision, position, probability) VALUES (?, ?, ?, ?)',
            ((*design.key, pos, fraction_text(p)) for pos, p in enumerate(schedule.probabilities, 1)),
        )
        return design

    def get_revision(self, key):
        key = revision_key(key, 'design')
        header = self.connection.execute(
            'SELECT length FROM design_revisions WHERE design_id = ? AND revision = ?', key
        ).fetchone()
        if header is None:
            raise KeyError(f'unknown design revision {key!r}')
        length, = header
        rows = self.connection.execute(
            'SELECT position, probability FROM design_probabilities '
            'WHERE design_id = ? AND revision = ? ORDER BY position', key
        ).fetchall()
        if [position for position, _ in rows] != list(range(1, length + 1)):
            raise ValueError('stored plan has incomplete positions')
        schedule = FixedSchedule(tuple(fraction_from_text(value) for _, value in rows))
        return FixedDesignRevision(*key, schedule)

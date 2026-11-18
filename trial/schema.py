SCHEMA_VERSION = 1


_TABLES = {
    'design_revisions': '''CREATE TABLE design_revisions (
        design_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision > 0),
        length INTEGER NOT NULL CHECK (length BETWEEN 1 AND 18),
        PRIMARY KEY (design_id, revision)
    )''',
    'design_probabilities': '''CREATE TABLE design_probabilities (
        design_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        position INTEGER NOT NULL CHECK (position BETWEEN 1 AND 18),
        probability TEXT NOT NULL,
        PRIMARY KEY (design_id, revision, position),
        FOREIGN KEY (design_id, revision) REFERENCES design_revisions (design_id, revision)
    )''',
    'trial_revisions': '''CREATE TABLE trial_revisions (
        trial_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision > 0),
        design_id TEXT NOT NULL,
        design_revision INTEGER NOT NULL,
        PRIMARY KEY (trial_id, revision),
        UNIQUE (trial_id, revision, design_id, design_revision),
        FOREIGN KEY (design_id, design_revision) REFERENCES design_revisions (design_id, revision)
    )''',
    'batch_records': '''CREATE TABLE batch_records (
        trial_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        batch_id TEXT NOT NULL,
        position INTEGER NOT NULL CHECK (position BETWEEN 1 AND 18),
        assignment TEXT NOT NULL CHECK (assignment IN ('A', 'B')),
        response INTEGER NOT NULL CHECK (response IN (0, 1)),
        PRIMARY KEY (trial_id, revision, position),
        UNIQUE (trial_id, revision, batch_id),
        FOREIGN KEY (trial_id, revision) REFERENCES trial_revisions (trial_id, revision)
    )''',
    'bindings': '''CREATE TABLE bindings (
        id INTEGER PRIMARY KEY,
        design_id TEXT NOT NULL,
        design_revision INTEGER NOT NULL,
        trial_id TEXT NOT NULL,
        trial_revision INTEGER NOT NULL,
        snapshot TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        FOREIGN KEY (trial_id, trial_revision, design_id, design_revision)
            REFERENCES trial_revisions (trial_id, revision, design_id, design_revision)
    )''',
    'replays': '''CREATE TABLE replays (
        id INTEGER PRIMARY KEY,
        binding_id INTEGER NOT NULL UNIQUE REFERENCES bindings (id),
        path_probability TEXT NOT NULL,
        statistic INTEGER NOT NULL CHECK (statistic BETWEEN -18 AND 18)
    )''',
    'replay_steps': '''CREATE TABLE replay_steps (
        replay_id INTEGER NOT NULL REFERENCES replays (id),
        position INTEGER NOT NULL CHECK (position BETWEEN 1 AND 18),
        probability TEXT NOT NULL,
        PRIMARY KEY (replay_id, position)
    )''',
    'reports': '''CREATE TABLE reports (
        id INTEGER PRIMARY KEY,
        replay_id INTEGER NOT NULL REFERENCES replays (id),
        statistic INTEGER NOT NULL CHECK (statistic BETWEEN -18 AND 18),
        tail_mass TEXT NOT NULL
    )''',
    'report_distribution': '''CREATE TABLE report_distribution (
        report_id INTEGER NOT NULL REFERENCES reports (id),
        statistic INTEGER NOT NULL CHECK (statistic BETWEEN -18 AND 18),
        mass TEXT NOT NULL,
        PRIMARY KEY (report_id, statistic)
    )''',
}


def _tables(connection):
    rows = connection.execute(
        "SELECT name, sql FROM sqlite_schema WHERE type = 'table' AND substr(name, 1, 7) <> 'sqlite_'"
    )
    return dict(rows)


def validate_schema_version(connection):
    version, = connection.execute('PRAGMA user_version').fetchone()
    if version != SCHEMA_VERSION:
        raise ValueError(f'unsupported archive schema version {version}')
    actual = _tables(connection)
    if actual.keys() != _TABLES.keys() or any(
        not actual[name] or actual[name].split() != sql.split() for name, sql in _TABLES.items()
    ):
        raise ValueError('archive tables do not match the current schema')
    return version


def initialize_schema(connection):
    if connection.in_transaction:
        raise RuntimeError('schema initialization requires an idle connection')
    connection.execute('PRAGMA foreign_keys = ON')
    if connection.execute('PRAGMA foreign_keys').fetchone() != (1,):
        raise RuntimeError('could not enable foreign keys')
    connection.execute('BEGIN IMMEDIATE')
    try:
        version, = connection.execute('PRAGMA user_version').fetchone()
        if version == 0:
            existing = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE substr(name, 1, 7) <> 'sqlite_' LIMIT 1"
            ).fetchone()
            if existing is not None:
                raise ValueError('unsupported nonempty unversioned archive')
            for sql in _TABLES.values():
                connection.execute(sql)
            connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        validate_schema_version(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise

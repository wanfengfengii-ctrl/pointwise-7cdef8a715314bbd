from contextlib import contextmanager


REPORT_HEADER = 'report_header'
REPORT_DISTRIBUTION = 'report_distribution'


class PublicationError(RuntimeError):
    pass


class Publication:
    def __init__(self, connection):
        self.connection = connection
        self._failure_stage = None
        self._failure_armed = False

    @contextmanager
    def transaction(self):
        if self.connection.in_transaction:
            raise RuntimeError('nested publication transaction')
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    @contextmanager
    def fail_at(self, stage):
        if stage not in (REPORT_HEADER, REPORT_DISTRIBUTION):
            raise ValueError('unknown report publication checkpoint')
        if self._failure_armed:
            raise RuntimeError('a publication failure scope is already active')
        self._failure_armed = True
        self._failure_stage = stage
        try:
            yield
        finally:
            self._failure_stage = None
            self._failure_armed = False

    def checkpoint(self, stage):
        if stage == self._failure_stage:
            self._failure_stage = None
            raise PublicationError(f'report publication failed at {stage}')

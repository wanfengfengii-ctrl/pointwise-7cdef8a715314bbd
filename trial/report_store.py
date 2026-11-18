from dataclasses import dataclass
from fractions import Fraction

from .codec import fraction_from_text, fraction_text
from .distribution import validate_distribution
from .publication import REPORT_DISTRIBUTION, REPORT_HEADER
from .revisions import positive_id
from .tails import validate_tail_mass


@dataclass(frozen=True, slots=True)
class FixedReport:
    id: int
    replay_id: int
    observed_statistic: int
    distribution: dict[int, Fraction]
    tail_mass: Fraction


def validate_report_values(report):
    if type(report.observed_statistic) is not int:
        raise ValueError('observed report statistic must be an integer')
    validate_distribution(report.distribution)
    if report.observed_statistic not in report.distribution:
        raise ValueError('observed statistic is outside the stored support')
    validate_tail_mass(report.distribution, report.observed_statistic, report.tail_mass)


class ReportStore:
    def __init__(self, connection, publication):
        self.connection = connection
        self.publication = publication

    def insert_report(self, replay_id, computation):
        replay_id = positive_id(replay_id, 'replay ID')
        validate_report_values(computation)
        cursor = self.connection.execute(
            'INSERT INTO reports (replay_id, statistic, tail_mass) VALUES (?, ?, ?)',
            (replay_id, computation.observed_statistic, fraction_text(computation.tail_mass)),
        )
        report_id = cursor.lastrowid
        self.publication.checkpoint(REPORT_HEADER)
        for index, (score, mass) in enumerate(sorted(computation.distribution.items())):
            self.connection.execute(
                'INSERT INTO report_distribution (report_id, statistic, mass) VALUES (?, ?, ?)',
                (report_id, score, fraction_text(mass)),
            )
            if index == 0:
                self.publication.checkpoint(REPORT_DISTRIBUTION)
        return FixedReport(report_id, replay_id, computation.observed_statistic,
                           dict(computation.distribution), computation.tail_mass)

    def get_report(self, report_id):
        report_id = positive_id(report_id, 'report ID')
        row = self.connection.execute(
            'SELECT r.replay_id, r.statistic, r.tail_mass, p.statistic FROM reports AS r '
            'LEFT JOIN replays AS p ON p.id = r.replay_id WHERE r.id = ?', (report_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f'unknown report {report_id}')
        replay_id, observed, tail, parent_statistic = row
        if parent_statistic is None or observed != parent_statistic:
            raise ValueError('report statistic has no matching parent replay')
        rows = self.connection.execute(
            'SELECT statistic, mass FROM report_distribution WHERE report_id = ? ORDER BY statistic', (report_id,)
        )
        distribution = {score: fraction_from_text(mass) for score, mass in rows}
        report = FixedReport(report_id, positive_id(replay_id, 'replay ID'), observed,
                             distribution, fraction_from_text(tail))
        validate_report_values(report)
        return report

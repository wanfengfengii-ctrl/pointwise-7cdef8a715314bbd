from .adaptive import (
    AdaptiveDesign,
    calculate_adaptive_report,
    normalize_assignments,
    normalize_responses,
    replay_path_probability,
    replay_value,
    report_value,
    walk_adaptive,
)


class AdaptiveService:
    def __init__(self, designs, replays, reports, publication):
        self.designs = designs
        self.replays = replays
        self.reports = reports
        self.publication = publication

    def save_adaptive(self, initial_a, initial_b, horizon, min_n, boundary):
        design = AdaptiveDesign(initial_a, initial_b, horizon, min_n, boundary)
        with self.publication.transaction():
            return self.designs.insert_design(design)

    def replay_adaptive(self, design_id, responses, assignments):
        design = self.designs.get_design(design_id)
        responses = normalize_responses(responses)
        assignments = normalize_assignments(assignments)
        steps = walk_adaptive(design, responses, assignments)
        path_probability = replay_path_probability(steps)
        statistic = steps[-1].statistic
        with self.publication.transaction():
            replay_id = self.replays.insert_replay(design_id, steps, path_probability, statistic)
        return replay_value(replay_id, design_id, design, steps, path_probability, statistic)

    def test_adaptive(self, replay_id):
        stored = self.replays.get_replay(replay_id)
        design = self.designs.get_design(stored.design_id)
        responses = tuple(step.response for step in stored.steps)
        computation = calculate_adaptive_report(design, responses, stored.statistic)
        with self.publication.transaction():
            report_id = self.reports.insert_report(stored.id, computation)
        return report_value(report_id, stored.id, computation)

    def read_adaptive_replay(self, replay_id):
        stored = self.replays.get_replay(replay_id)
        design = self.designs.get_design(stored.design_id)
        return replay_value(stored.id, stored.design_id, design, stored.steps,
                            stored.path_probability, stored.statistic)

    def read_adaptive_report(self, report_id):
        return self.reports.get_report(report_id)

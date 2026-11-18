from fractions import Fraction as F
from pathlib import Path
from tempfile import TemporaryDirectory

from trial.archive import TrialArchive


CASES = (
    ("four_at_horizon", (1, 1, 4, 4, 4), (1, 1, 1, 1), "AAAA",
     (F(1, 5), 4, F(1), F(2, 5), F(2, 5))),
    ("four_before_horizon", (1, 1, 6, 4, 4), (1, 1, 1, 1), "AAAA",
     (F(1, 5), 4, F(2, 5), F(2, 5), F(1))),
    ("earlier_stops_excluded", (1, 1, 4, 2, 2), (1, 1, 1, 1), "ABAA",
     (F(1, 20), 2, F(1, 3), F(1, 5), F(3, 5))),
    ("mixed_responses", (1, 1, 4, 2, 2), (1, 0, 1, 1), "ABBA",
     (F(1, 40), 1, F(5, 12), F(5, 12), F(1))),
)


def main():
    with TemporaryDirectory() as directory:
        database = Path(directory) / "adaptive.sqlite"
        history = {}
        with TrialArchive.open(database) as archive:
            for name, design, responses, assignments, expected in CASES:
                design_id = archive.save_adaptive(*design)
                replay = archive.replay_adaptive(design_id, responses, assignments)
                report = archive.test_adaptive(replay["id"])
                actual = (replay["path_probability"], replay["statistic"], report["stop_mass"],
                          report["joint_tail_mass"], report["conditional_tail"])
                if actual != expected:
                    raise AssertionError(f"{name}: expected {expected}, got {actual}")
                history[name] = replay, report
                print(name, *(str(value) for value in actual))
            original, _ = history["four_at_horizon"]
            corrected = archive.replay_adaptive(original["design_id"], (1, 1, 1, 0), "AAAA")
            corrected_report = archive.test_adaptive(corrected["id"])
            if corrected_report["conditional_tail"] != F(1, 2):
                raise AssertionError("the corrected tail must be 1/2")
            history["correction"] = corrected, corrected_report
        with TrialArchive.open(database) as archive:
            for name, (replay, report) in history.items():
                if archive.read_adaptive_replay(replay["id"]) != replay:
                    raise AssertionError(f"{name}: reopened replay changed")
                saved = archive.read_adaptive_report(report["id"])
                if saved != report:
                    raise AssertionError(f"{name}: reopened report changed")
                print(name, "reopened", saved["id"], str(saved["conditional_tail"]))


if __name__ == "__main__":
    main()

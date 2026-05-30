from __future__ import annotations

from dataclasses import dataclass

from experiments.curse_detector_benchmark.cases import BAD_WORDS, CASES, CurseCase
from experiments.curse_detector_benchmark.detectors import CurseDetector, build_detectors


@dataclass
class DetectorStats:
    name: str
    total: int = 0
    passed: int = 0
    false_positive: int = 0
    false_negative: int = 0
    skipped: int = 0
    failures: list[str] | None = None

    def __post_init__(self) -> None:
        if self.failures is None:
            self.failures = []


def evaluate_detector(detector: CurseDetector, cases: list[CurseCase]) -> DetectorStats:
    stats = DetectorStats(name=detector.name)
    for case in cases:
        stats.total += 1
        result = detector.detect(case.text, BAD_WORDS)

        if result.skipped_reason is not None:
            stats.skipped += 1
            if stats.failures is not None and len(stats.failures) == 0:
                stats.failures.append(f"SKIPPED: {result.skipped_reason}")
            continue

        if result.detected == case.expected:
            stats.passed += 1
            continue

        if result.detected and not case.expected:
            stats.false_positive += 1
            kind = "FALSE POSITIVE"
        else:
            stats.false_negative += 1
            kind = "FALSE NEGATIVE"

        if stats.failures is not None:
            matched = ", ".join(result.matched) if result.matched else "-"
            stats.failures.append(
                f"{kind}: {case.name}: expected={case.expected} "
                f"actual={result.detected} matched={matched} text={case.text!r} note={case.note}"
            )
    return stats


def print_summary(stats: list[DetectorStats]) -> None:
    print("Bad words:", ", ".join(BAD_WORDS))
    print()
    print(f"{'detector':28} {'passed':>8} {'failed':>8} {'fp':>4} {'fn':>4} {'skipped':>8}")
    print("-" * 68)
    for item in stats:
        failed = item.false_positive + item.false_negative
        print(
            f"{item.name:28} {item.passed:>8}/{item.total:<3} "
            f"{failed:>8} {item.false_positive:>4} {item.false_negative:>4} {item.skipped:>8}"
        )


def print_failures(stats: list[DetectorStats]) -> None:
    print()
    print("Failures:")
    for item in stats:
        if not item.failures:
            continue
        print()
        print(f"[{item.name}]")
        for failure in item.failures:
            print("-", failure)


def main() -> None:
    detectors = build_detectors()
    stats = [evaluate_detector(detector, CASES) for detector in detectors]
    print_summary(stats)
    print_failures(stats)


if __name__ == "__main__":
    main()

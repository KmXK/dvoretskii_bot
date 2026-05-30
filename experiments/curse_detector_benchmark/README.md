# Curse Detector Benchmark

This is a local, uncommitted experiment for comparing Russian curse-word detectors.

Run with current project dependencies:

```bash
python3 -m experiments.curse_detector_benchmark.run
```

Project-version isolated run:

```bash
/opt/homebrew/bin/python3.12 -m venv experiments/curse_detector_benchmark/.venv312
experiments/curse_detector_benchmark/.venv312/bin/python -m pip install pymorphy3 crosstem glin-profanity better-profanity
experiments/curse_detector_benchmark/.venv312/bin/python -m experiments.curse_detector_benchmark.run
```

The benchmark uses one shared configurable bad-word list from `cases.py` and runs every detector on the same positive and negative cases.

The production bot code is not imported or modified.

# Curse Detector Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an uncommitted, standalone benchmark that compares Russian curse-word detectors against the same configurable word list and the same positive/negative test cases.

**Architecture:** The benchmark lives outside the production bot code in `experiments/curse_detector_benchmark/`. A small shared interface normalizes each detector implementation to `detect(text, bad_words) -> DetectionResult`; `run.py` loads all available implementations, skips missing optional libraries, runs one shared case table, and prints a comparable result report.

**Tech Stack:** Python 3.12, existing `pymorphy3`, optional `glin-profanity`, optional `better-profanity`, optional `profanity-filter`.

---

## File Structure

- Create: `experiments/curse_detector_benchmark/__init__.py`
  - Empty package marker for local imports.
- Create: `experiments/curse_detector_benchmark/cases.py`
  - Stores the shared configurable bad-word list and the shared test cases.
- Create: `experiments/curse_detector_benchmark/detectors.py`
  - Defines the common detector protocol, result dataclass, and one adapter per library.
- Create: `experiments/curse_detector_benchmark/run.py`
  - Runs every available detector against every case and prints a summary table plus failures.
- Create: `experiments/curse_detector_benchmark/README.md`
  - Explains how to run the benchmark and how to install optional libraries.

No production files are modified. No commits are made for this experiment.

---

### Task 1: Create Shared Cases

**Files:**
- Create: `experiments/curse_detector_benchmark/__init__.py`
- Create: `experiments/curse_detector_benchmark/cases.py`

- [ ] **Step 1: Create package marker**

Create `experiments/curse_detector_benchmark/__init__.py` as an empty file.

- [ ] **Step 2: Add shared case definitions**

Create `experiments/curse_detector_benchmark/cases.py` with:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class CurseCase:
    name: str
    text: str
    expected: bool
    note: str


BAD_WORDS = [
    "хуй",
    "пизда",
    "ебать",
    "блядь",
    "сука",
]


CASES = [
    CurseCase(
        name="direct_nominative",
        text="хуй",
        expected=True,
        note="Exact dictionary form should be detected.",
    ),
    CurseCase(
        name="direct_in_sentence",
        text="ну это пизда какая-то",
        expected=True,
        note="Exact bad word inside sentence.",
    ),
    CurseCase(
        name="case_insensitive",
        text="БЛЯДЬ, опять сломалось",
        expected=True,
        note="Uppercase token with punctuation.",
    ),
    CurseCase(
        name="inflected_genitive",
        text="без хуя тут не разобраться",
        expected=True,
        note="Inflected noun form should match base lemma.",
    ),
    CurseCase(
        name="inflected_plural",
        text="эти суки опять шумят",
        expected=True,
        note="Plural inflection should match singular lemma.",
    ),
    CurseCase(
        name="verb_inflection",
        text="он опять ебался с настройками",
        expected=True,
        note="Verb form should match configured verb lemma.",
    ),
    CurseCase(
        name="derived_adjective",
        text="какая-то хуевая ситуация",
        expected=True,
        note="Derived adjective is useful to compare; pure lemmatizers may miss it.",
    ),
    CurseCase(
        name="compound_word",
        text="это пиздец полный",
        expected=True,
        note="Derived/compound profanity; configurable detectors may need extra dictionary entry.",
    ),
    CurseCase(
        name="normal_word_suka_sound",
        text="у меня болит скула",
        expected=False,
        note="Looks somewhat close to 'сука' but is normal.",
    ),
    CurseCase(
        name="normal_word_hutor",
        text="мы едем на хутор вечером",
        expected=False,
        note="Starts similarly to a bad root but is normal.",
    ),
    CurseCase(
        name="normal_word_blago",
        text="благодаря тебе всё получилось",
        expected=False,
        note="Starts similarly to a profanity prefix but is normal.",
    ),
    CurseCase(
        name="command_should_be_ignored_by_backend_policy",
        text="/curse word_list add хуй",
        expected=False,
        note="Matches current bot policy: commands are not auto-counted.",
    ),
    CurseCase(
        name="clean_sentence",
        text="сегодня хороший день и вкусный кофе",
        expected=False,
        note="Plain clean sentence.",
    ),
]
```

- [ ] **Step 3: Sanity-check import**

Run:

```bash
python -m py_compile experiments/curse_detector_benchmark/cases.py
```

Expected: command exits with code `0`.

---

### Task 2: Implement Detector Interface And Adapters

**Files:**
- Create: `experiments/curse_detector_benchmark/detectors.py`

- [ ] **Step 1: Add detector implementations**

Create `experiments/curse_detector_benchmark/detectors.py` with:

```python
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from typing import Protocol


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+", re.UNICODE)


@dataclass(frozen=True)
class DetectionResult:
    detected: bool
    matched: tuple[str, ...] = ()
    skipped_reason: str | None = None


class CurseDetector(Protocol):
    name: str

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        pass


def _tokens(text: str) -> list[str]:
    if text.startswith("/"):
        return []
    return [token.lower().replace("ё", "е") for token in TOKEN_RE.findall(text)]


def _normalize_words(words: list[str]) -> set[str]:
    return {word.lower().replace("ё", "е") for word in words}


class ExactTokenDetector:
    name = "exact-token-baseline"

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        bad = _normalize_words(bad_words)
        matched = tuple(token for token in _tokens(text) if token in bad)
        return DetectionResult(detected=bool(matched), matched=matched)


class PymorphyDetector:
    name = "pymorphy3-custom-dict"

    def __init__(self) -> None:
        pymorphy3 = importlib.import_module("pymorphy3")
        self._morph = pymorphy3.MorphAnalyzer()

    def _forms(self, word: str) -> set[str]:
        forms = {word}
        for parsed in self._morph.parse(word):
            forms.add(parsed.normal_form.replace("ё", "е"))
        return forms

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        bad_forms: set[str] = set()
        for word in _normalize_words(bad_words):
            bad_forms.update(self._forms(word))

        matched: list[str] = []
        for token in _tokens(text):
            if self._forms(token) & bad_forms:
                matched.append(token)
        return DetectionResult(detected=bool(matched), matched=tuple(matched))


class GlinProfanityDetector:
    name = "glin-profanity"

    def __init__(self) -> None:
        module = importlib.import_module("glin_profanity")
        self._module = module

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        if text.startswith("/"):
            return DetectionResult(detected=False)

        if hasattr(self._module, "GlinProfanity"):
            detector = self._module.GlinProfanity(custom_words=bad_words)
            detected = bool(detector.contains_profanity(text))
            return DetectionResult(detected=detected)

        if hasattr(self._module, "contains_profanity"):
            detected = bool(self._module.contains_profanity(text, custom_words=bad_words))
            return DetectionResult(detected=detected)

        return DetectionResult(
            detected=False,
            skipped_reason="Unsupported glin_profanity API shape",
        )


class BetterProfanityDetector:
    name = "better-profanity"

    def __init__(self) -> None:
        module = importlib.import_module("better_profanity")
        self._profanity = module.profanity

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        if text.startswith("/"):
            return DetectionResult(detected=False)

        self._profanity.load_censor_words(custom_words=bad_words)
        detected = bool(self._profanity.contains_profanity(text))
        return DetectionResult(detected=detected)


class ProfanityFilterDetector:
    name = "profanity-filter"

    def __init__(self) -> None:
        module = importlib.import_module("profanity_filter")
        self._class = module.ProfanityFilter

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        if text.startswith("/"):
            return DetectionResult(detected=False)

        detector = self._class(custom_profane_word_dictionaries={"ru": bad_words})
        detected = bool(detector.is_profane(text))
        return DetectionResult(detected=detected)


def build_detectors() -> list[CurseDetector]:
    detectors: list[CurseDetector] = [
        ExactTokenDetector(),
        PymorphyDetector(),
    ]

    optional_classes = [
        GlinProfanityDetector,
        BetterProfanityDetector,
        ProfanityFilterDetector,
    ]
    for cls in optional_classes:
        try:
            detectors.append(cls())
        except Exception as error:
            detectors.append(_SkippedDetector(cls.name, str(error)))
    return detectors


class _SkippedDetector:
    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self._reason = reason

    def detect(self, text: str, bad_words: list[str]) -> DetectionResult:
        return DetectionResult(
            detected=False,
            skipped_reason=self._reason,
        )
```

- [ ] **Step 2: Sanity-check import**

Run:

```bash
python -m py_compile experiments/curse_detector_benchmark/detectors.py
```

Expected: command exits with code `0`.

- [ ] **Step 3: Verify required detector can load**

Run:

```bash
python - <<'PY'
from experiments.curse_detector_benchmark.detectors import PymorphyDetector
detector = PymorphyDetector()
print(detector.detect("без хуя", ["хуй"]))
PY
```

Expected: output contains `detected=True`.

---

### Task 3: Implement Benchmark Runner

**Files:**
- Create: `experiments/curse_detector_benchmark/run.py`

- [ ] **Step 1: Add runner**

Create `experiments/curse_detector_benchmark/run.py` with:

```python
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
```

- [ ] **Step 2: Run benchmark with existing dependencies**

Run:

```bash
python -m experiments.curse_detector_benchmark.run
```

Expected:
- `exact-token-baseline` runs.
- `pymorphy3-custom-dict` runs.
- optional libraries either run or show `SKIPPED`.
- The command exits with code `0`.

---

### Task 4: Add Local Experiment README

**Files:**
- Create: `experiments/curse_detector_benchmark/README.md`

- [ ] **Step 1: Add README**

Create `experiments/curse_detector_benchmark/README.md` with:

```markdown
# Curse Detector Benchmark

This is a local, uncommitted experiment for comparing Russian curse-word detectors.

Run with current project dependencies:

```bash
python -m experiments.curse_detector_benchmark.run
```

Optional libraries:

```bash
python -m pip install glin-profanity better-profanity profanity-filter
python -m experiments.curse_detector_benchmark.run
```

The benchmark uses one shared configurable bad-word list from `cases.py` and runs every detector on the same positive and negative cases.

The production bot code is not imported or modified.
```

- [ ] **Step 2: Confirm README renders as plain Markdown**

Run:

```bash
sed -n '1,120p' experiments/curse_detector_benchmark/README.md
```

Expected: README text prints, including the two command blocks.

---

### Task 5: Optional Dependency Run

**Files:**
- No file changes.

- [ ] **Step 1: Run baseline benchmark first**

Run:

```bash
python -m experiments.curse_detector_benchmark.run
```

Expected: baseline and `pymorphy3-custom-dict` produce real results.

- [ ] **Step 2: Install optional packages only if the user approves network/write access**

Run:

```bash
python -m pip install glin-profanity better-profanity profanity-filter
```

Expected:
- If installation succeeds, rerun the benchmark.
- If installation fails because a package is incompatible with Python 3.12, leave the failure visible in the final comparison notes.

- [ ] **Step 3: Run full benchmark**

Run:

```bash
python -m experiments.curse_detector_benchmark.run
```

Expected:
- Every installable detector produces a row.
- Incompatible detectors are skipped with a reason instead of crashing the benchmark.

---

### Task 6: Interpret Results

**Files:**
- No file changes.

- [ ] **Step 1: Summarize detector quality**

Use the benchmark output to classify each detector:

```text
Recommended:
- detector-name: why it handled Russian forms and avoided false positives.

Usable with caveats:
- detector-name: specific missed cases or false positives.

Not suitable:
- detector-name: installation failure, API incompatibility, or poor result profile.
```

- [ ] **Step 2: Recommend production direction**

Use this decision rule:

```text
Choose pymorphy3-custom-dict if it detects normal inflections and has fewer false positives than fuzzy libraries.
Choose glin-profanity only if it substantially improves derived/obfuscated cases without introducing false positives.
Reject libraries that cannot use a custom word list or cannot run on Python 3.12.
```

- [ ] **Step 3: Leave experiment uncommitted**

Run:

```bash
git status --short
```

Expected: `experiments/curse_detector_benchmark/` and this plan are untracked or modified locally. Do not commit them.

---

## Self-Review

- Spec coverage: The plan creates a standalone benchmark, uses one configurable bad-word list, runs shared positive and negative cases across all detectors, skips missing optional dependencies, and produces a comparable report.
- Placeholder scan: No placeholder markers or undefined follow-up instructions remain.
- Type consistency: `CurseCase`, `DetectionResult`, `CurseDetector`, `DetectorStats`, and `build_detectors()` are defined before use and have consistent names across tasks.

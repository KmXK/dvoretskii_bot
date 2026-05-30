# Curse Backend Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace exact-token curse detection with a configurable Russian-aware detector based on `pymorphy3 + crosstem`, while preserving existing curse metrics/punishment behavior and adding an admin-managed ignore word list.

**Architecture:** Keep the feature framework shape introduced by the latest remote changes: `/curse` commands remain in `steward/features/curse.py`, passive message counting remains in `steward/features/curse_metric.py`, and reusable matching logic moves into a focused helper `steward/helpers/curse_detector.py`. The database gains `curse_ignore_words`, with migration/version updates; `CurseMetricFeature` delegates count logic to the new helper and keeps writing the same `bot_curse_words_total` metric.

**Tech Stack:** Python 3.12, existing feature framework, `pymorphy3`, new dependency `crosstem`, existing pytest test harness.

---

## Current Context Snapshot

The repository has changed after the latest pull:

- Curse command implementation is now [steward/features/curse.py](/Users/ivanmautin/projects/dvoretskii_bot/steward/features/curse.py), not the old `steward/handlers/curse_handler.py`.
- Passive curse counting is now [steward/features/curse_metric.py](/Users/ivanmautin/projects/dvoretskii_bot/steward/features/curse_metric.py).
- Database version is currently `34` in [steward/data/models/db.py](/Users/ivanmautin/projects/dvoretskii_bot/steward/data/models/db.py).
- Existing curse fields are `curse_words`, `curse_punishments`, and `curse_participants`.
- Existing tests are [tests/test_curse_metric_handler.py](/Users/ivanmautin/projects/dvoretskii_bot/tests/test_curse_metric_handler.py), [tests/test_curse_handler.py](/Users/ivanmautin/projects/dvoretskii_bot/tests/test_curse_handler.py), and [tests/test_curse_repository.py](/Users/ivanmautin/projects/dvoretskii_bot/tests/test_curse_repository.py).

Do not use old handler paths in implementation.

---

## File Structure

- Create: `steward/helpers/curse_detector.py`
  - Pure-ish detector helper: tokenization, bad-word form expansion, ignore-word form expansion, count API.
- Modify: `steward/features/curse_metric.py`
  - Replace exact `text.split()` counter with `CurseDetector.count(...)`.
  - Add `curse_ignore_words = collection("curse_ignore_words")`.
- Modify: `steward/features/curse.py`
  - Add `curse_ignore_words = collection("curse_ignore_words")`.
  - Add `/curse ignore_list`, `/curse ignore_list add <words>`, `/curse ignore_list remove <words>`.
- Modify: `steward/data/models/db.py`
  - Add `curse_ignore_words: set[str]`.
  - Bump `version` from `34` to `35`.
- Modify: `steward/data/repository.py`
  - Add migration `34 -> 35`.
  - Add idempotent fix-up for `curse_ignore_words`.
- Modify: `requirements.txt`
  - Add `crosstem`.
- Modify: `tests/test_curse_metric_handler.py`
  - Add detector behavior tests: inflections, derivations, close clean words, ignore list precedence.
- Modify: `tests/test_curse_handler.py`
  - Add ignore-list command tests.
- Modify: `tests/test_curse_repository.py`
  - Add migration test for `curse_ignore_words`.

---

### Task 1: Add Database Field And Migration

**Files:**
- Modify: `steward/data/models/db.py`
- Modify: `steward/data/repository.py`
- Test: `tests/test_curse_repository.py`

- [ ] **Step 1: Write failing migration test**

Append this test to `tests/test_curse_repository.py`:

```python
    async def test_migrate_adds_curse_ignore_words(self):
        repo = make_repository()

        migrated = repo._migrate({"version": 34, "admin_ids": []})

        assert migrated["version"] >= 35
        assert migrated["curse_ignore_words"] == []
```

- [ ] **Step 2: Run migration test and verify it fails**

Run:

```bash
pytest tests/test_curse_repository.py::TestCurseRepositoryMigration::test_migrate_adds_curse_ignore_words -q
```

Expected: fails with `KeyError: 'curse_ignore_words'` or `assert 34 >= 35`.

- [ ] **Step 3: Add database field and bump version**

In `steward/data/models/db.py`, add the new field next to `curse_words`:

```python
    curse_words: set[str] = field(default_factory=set)
    curse_ignore_words: set[str] = field(default_factory=set)
```

Change:

```python
    version: int = 34
```

to:

```python
    version: int = 35
```

- [ ] **Step 4: Add migration and idempotent fix-up**

In `steward/data/repository.py`, after the existing `if data.get("version") == 33:` block:

```python
        if data.get("version") == 34:
            if "curse_ignore_words" not in data or not isinstance(data["curse_ignore_words"], list):
                data["curse_ignore_words"] = []
            data["version"] = 35
```

In the idempotent fix-up section before `return data`, add:

```python
        if "curse_ignore_words" not in data or not isinstance(data["curse_ignore_words"], list):
            data["curse_ignore_words"] = []
```

- [ ] **Step 5: Run migration tests**

Run:

```bash
pytest tests/test_curse_repository.py -q
```

Expected: all tests in `tests/test_curse_repository.py` pass.

---

### Task 2: Add Detector Helper

**Files:**
- Create: `steward/helpers/curse_detector.py`
- Test: `tests/test_curse_metric_handler.py`

- [ ] **Step 1: Write failing detector behavior tests**

Append these tests to `tests/test_curse_metric_handler.py`:

```python
    async def test_counts_inflected_and_derived_curse_words(self):
        repo = make_repository()
        repo.db.curse_words = {"хуй", "пизда", "ебать", "сука"}
        metrics = MagicMock()
        feature = _make_feature(repo)

        ctx = make_text_context(
            "без хуя эти суки сказали что это хуевая ситуация и пиздец, он ебался",
            repo=repo,
            metrics=metrics,
        )
        ok = await feature.chat(ctx)

        assert not ok
        metrics.inc.assert_called_once_with("bot_curse_words_total", value=5)

    async def test_does_not_count_close_clean_words(self):
        repo = make_repository()
        repo.db.curse_words = {"хуй", "пизда", "ебать", "блядь", "сука"}
        metrics = MagicMock()
        feature = _make_feature(repo)

        ctx = make_text_context(
            "бляха бляшка блямба сукно скула хутор благодаря",
            repo=repo,
            metrics=metrics,
        )
        ok = await feature.chat(ctx)

        assert not ok
        metrics.inc.assert_not_called()

    async def test_ignore_words_suppress_only_exact_morphological_family(self):
        repo = make_repository()
        repo.db.curse_words = {"пизда"}
        repo.db.curse_ignore_words = {"пиздец"}
        metrics = MagicMock()
        feature = _make_feature(repo)

        ignored_ctx = make_text_context("это пиздеца полный", repo=repo, metrics=metrics)
        bad_ctx = make_text_context("ну это пизда какая-то", repo=repo, metrics=metrics)

        await feature.chat(ignored_ctx)
        await feature.chat(bad_ctx)

        metrics.inc.assert_called_once_with("bot_curse_words_total", value=1)
```

- [ ] **Step 2: Run new tests and verify they fail**

Run:

```bash
pytest tests/test_curse_metric_handler.py::TestCurseMetricFeature::test_counts_inflected_and_derived_curse_words tests/test_curse_metric_handler.py::TestCurseMetricFeature::test_does_not_count_close_clean_words tests/test_curse_metric_handler.py::TestCurseMetricFeature::test_ignore_words_suppress_only_exact_morphological_family -q
```

Expected: at least the inflection/derivation and ignore tests fail under the current exact-token counter.

- [ ] **Step 3: Implement detector helper**

Create `steward/helpers/curse_detector.py`:

```python
import re
from functools import cached_property, lru_cache

import crosstem
import pymorphy3


_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+", re.UNICODE)


def _norm(word: str) -> str:
    return word.lower().replace("ё", "е")


class CurseDetector:
    @cached_property
    def _morph(self):
        return pymorphy3.MorphAnalyzer()

    @cached_property
    def _stemmer(self):
        return crosstem.DerivationalStemmer("rus")

    def count(
        self,
        text: str,
        bad_words: set[str],
        ignore_words: set[str] | None = None,
    ) -> int:
        if not text or text.startswith("/") or not bad_words:
            return 0

        bad_forms = self._bad_forms(frozenset(_norm(w) for w in bad_words))
        ignore_forms = self._ignore_forms(frozenset(_norm(w) for w in (ignore_words or set())))

        count = 0
        for token in self._tokens(text):
            token_forms = self._all_forms(token)
            if token_forms & ignore_forms:
                continue
            if token_forms & bad_forms:
                count += 1
        return count

    def _tokens(self, text: str) -> list[str]:
        return [_norm(token) for token in _TOKEN_RE.findall(text)]

    @lru_cache(maxsize=4096)
    def _pymorphy_forms(self, word: str) -> frozenset[str]:
        forms = {word}
        for parsed in self._morph.parse(word):
            forms.add(_norm(parsed.normal_form))
        return frozenset(forms)

    @lru_cache(maxsize=4096)
    def _all_forms(self, word: str) -> frozenset[str]:
        forms = set(self._pymorphy_forms(word))
        for form in list(forms):
            try:
                forms.add(_norm(self._stemmer.stem(form)))
            except Exception:
                pass
        return frozenset(forms)

    @lru_cache(maxsize=128)
    def _bad_forms(self, words: frozenset[str]) -> frozenset[str]:
        forms: set[str] = set()
        for word in words:
            forms.update(self._all_forms(word))
        return frozenset(forms)

    @lru_cache(maxsize=128)
    def _ignore_forms(self, words: frozenset[str]) -> frozenset[str]:
        forms: set[str] = set()
        for word in words:
            forms.update(self._pymorphy_forms(word))
        return frozenset(forms)
```

- [ ] **Step 4: Run detector helper syntax check**

Run:

```bash
python -m py_compile steward/helpers/curse_detector.py
```

Expected: command exits with code `0`.

---

### Task 3: Wire Detector Into Passive Metric Feature

**Files:**
- Modify: `steward/features/curse_metric.py`
- Test: `tests/test_curse_metric_handler.py`

- [ ] **Step 1: Modify `CurseMetricFeature` collections and counter**

Replace `steward/features/curse_metric.py` with:

```python
from steward.framework import Feature, FeatureContext, collection, on_message
from steward.helpers.curse_detector import CurseDetector


class CurseMetricFeature(Feature):
    curse_words = collection("curse_words")
    curse_ignore_words = collection("curse_ignore_words")

    def __init__(self):
        super().__init__()
        self._detector = CurseDetector()

    @on_message
    async def count(self, ctx: FeatureContext) -> bool:
        if ctx.message is None:
            return False
        text = ctx.message.text
        if not text or text.startswith("/"):
            return False
        if getattr(ctx.message, "forward_origin", None) is not None:
            return False
        words = self.curse_words.all()
        if not words:
            return False
        count = self._detector.count(
            text,
            set(words),
            set(self.curse_ignore_words.all()),
        )
        if count > 0:
            ctx.metrics.inc("bot_curse_words_total", value=count)
        return False
```

- [ ] **Step 2: Run curse metric tests**

Run:

```bash
pytest tests/test_curse_metric_handler.py -q
```

Expected: all tests in `tests/test_curse_metric_handler.py` pass.

---

### Task 4: Add Ignore List Commands

**Files:**
- Modify: `steward/features/curse.py`
- Test: `tests/test_curse_handler.py`

- [ ] **Step 1: Write failing command tests**

Append this class to `tests/test_curse_handler.py` after `TestCurseWordList`:

```python
class TestCurseIgnoreList:
    async def test_empty_ignore_list(self):
        reply, ok = await invoke(CurseFeature, "/curse ignore_list", make_repository())
        assert ok
        assert "исключ" in reply.lower()
        assert "пуст" in reply.lower()

    async def test_adds_ignore_words_for_admin(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        reply, ok = await invoke(CurseFeature, "/curse ignore_list add Пиздец БЛЯХА", repo)
        assert ok
        assert repo.db.curse_ignore_words == {"пиздец", "бляха"}
        assert "Добавлены" in reply

    async def test_removes_ignore_words_for_admin(self):
        repo = make_repository()
        repo.db.admin_ids = {DEFAULT_USER_ID}
        repo.db.curse_ignore_words = {"пиздец", "бляха"}
        reply, ok = await invoke(CurseFeature, "/curse ignore_list remove бляха", repo)
        assert ok
        assert repo.db.curse_ignore_words == {"пиздец"}
        assert "Удалены" in reply

    async def test_rejects_ignore_add_for_non_admin(self):
        reply, ok = await invoke(CurseFeature, "/curse ignore_list add бляха", make_repository())
        assert ok
        assert "прав" in reply.lower()
```

- [ ] **Step 2: Run new command tests and verify they fail**

Run:

```bash
pytest tests/test_curse_handler.py::TestCurseIgnoreList -q
```

Expected: fails because `ignore_list` subcommands do not exist or `curse_ignore_words` is missing before Task 1 is implemented.

- [ ] **Step 3: Add collection and subcommands**

In `steward/features/curse.py`, add a collection near `curse_words`:

```python
    curse_ignore_words = collection("curse_ignore_words")
```

Add these subcommands after `remove_words`:

```python
    @subcommand("ignore_list", description="Список исключений для матных слов")
    async def show_ignore_list(self, ctx: FeatureContext):
        words = sorted(self.curse_ignore_words.all())
        if not words:
            await ctx.reply("Список исключений пуст.")
            return
        await ctx.reply("Исключения:\n\n" + "\n".join(words))

    @subcommand("ignore_list add <words:rest>", description="Добавить исключения", admin=True)
    async def add_ignore_words(self, ctx: FeatureContext, words: str):
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()
        added = self.curse_ignore_words.add_many(items)
        if not added:
            await ctx.reply("Все исключения уже есть в списке.")
            return
        await self.curse_ignore_words.save()
        await ctx.reply("Добавлены исключения: " + ", ".join(added))

    @subcommand("ignore_list remove <words:rest>", description="Удалить исключения", admin=True)
    async def remove_ignore_words(self, ctx: FeatureContext, words: str):
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()
        removed = self.curse_ignore_words.remove_many(items)
        if not removed:
            await ctx.reply("Ни одно исключение не найдено в списке.")
            return
        await self.curse_ignore_words.save()
        await ctx.reply("Удалены исключения: " + ", ".join(removed))
```

- [ ] **Step 4: Run curse command tests**

Run:

```bash
pytest tests/test_curse_handler.py -q
```

Expected: all tests in `tests/test_curse_handler.py` pass.

---

### Task 5: Add Dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add crosstem dependency**

Add a new line to `requirements.txt` near `pymorphy3`:

```text
crosstem
```

- [ ] **Step 2: Verify dependency import in project Python**

Run:

```bash
python -c "import crosstem; from crosstem import DerivationalStemmer; print(DerivationalStemmer('rus').stem('хуевый'))"
```

Expected: output is `хуй`.

If the local environment does not have fresh dependencies installed, run the same import check after installing requirements in the active virtualenv used for project tests.

---

### Task 6: Full Verification

**Files:**
- No additional file changes.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_curse_repository.py tests/test_curse_metric_handler.py tests/test_curse_handler.py -q
```

Expected: all focused curse tests pass.

- [ ] **Step 2: Run startup test**

Run:

```bash
pytest tests/test_startup.py -q
```

Expected: startup/feature registry tests pass, proving the new `curse_ignore_words` collection does not break feature initialization.

- [ ] **Step 3: Run broader test suite if time allows**

Run:

```bash
pytest -q
```

Expected: full suite passes. If unrelated failures appear, record exact failing tests and verify the focused curse tests still pass.

- [ ] **Step 4: Check uncommitted changes**

Run:

```bash
git status --short
```

Expected: only intentional files are modified or untracked:

```text
M requirements.txt
M steward/data/models/db.py
M steward/data/repository.py
M steward/features/curse.py
M steward/features/curse_metric.py
A steward/helpers/curse_detector.py
M tests/test_curse_handler.py
M tests/test_curse_metric_handler.py
M tests/test_curse_repository.py
```

Existing untracked experiment/plan files may also remain from the benchmark work.

---

## Self-Review

- Spec coverage: The plan migrates detection to `pymorphy3 + crosstem`, preserves current metrics/punishments, adds configurable `ignore_list`, preserves command/forwarded-message skip behavior, adds DB migration, and verifies focused tests.
- Placeholder scan: No placeholder markers or undefined follow-up instructions remain.
- Type consistency: `curse_ignore_words`, `CurseDetector.count`, `CurseFeature`, and `CurseMetricFeature` names are consistent across code and tests.
- Current-repo alignment: The plan uses the post-pull feature framework paths (`steward/features/...`) and avoids obsolete handler paths.

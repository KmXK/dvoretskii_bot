from unittest.mock import MagicMock

from steward.features.curse_metric import CurseMetricFeature
from tests.conftest import make_repository, make_text_context


def _make_feature(repo):
    feature = CurseMetricFeature()
    feature.repository = repo
    feature.bot = MagicMock()
    return feature


class TestCurseMetricFeature:
    async def test_counts_multiple_words_case_insensitively(self):
        repo = make_repository()
        repo.db.curse_words = {"мат"}
        metrics = MagicMock()
        feature = _make_feature(repo)

        ctx = make_text_context("Мат привет мат", repo=repo, metrics=metrics)
        ok = await feature.chat(ctx)

        assert not ok
        metrics.inc.assert_called_once_with("bot_curse_words_total", value=2)

    async def test_skips_forwarded_messages(self):
        repo = make_repository()
        repo.db.curse_words = {"мат"}
        metrics = MagicMock()
        feature = _make_feature(repo)

        ctx = make_text_context("мат", repo=repo, metrics=metrics)
        ctx.message.forward_origin = object()
        ok = await feature.chat(ctx)

        assert not ok
        metrics.inc.assert_not_called()

    async def test_skips_commands(self):
        repo = make_repository()
        repo.db.curse_words = {"мат"}
        metrics = MagicMock()
        feature = _make_feature(repo)

        cmd_ctx = make_text_context("/curse word_list add мат", repo=repo, metrics=metrics)
        await feature.chat(cmd_ctx)

        metrics.inc.assert_not_called()

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

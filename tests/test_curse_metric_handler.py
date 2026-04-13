from unittest.mock import MagicMock

from tests.conftest import make_repository, make_text_context


def _make_handler(repo):
    from steward.handlers.curse_metric_handler import CurseMetricHandler

    handler = CurseMetricHandler()
    handler.repository = repo
    handler.bot = MagicMock()
    return handler


class TestCurseMetricHandler:
    async def test_counts_multiple_words_case_insensitively(self):
        repo = make_repository()
        repo.db.curse_words = {"мат"}
        metrics = MagicMock()
        handler = _make_handler(repo)

        ctx = make_text_context("Мат привет мат", repo=repo, metrics=metrics)
        ok = await handler.chat(ctx)

        assert not ok
        metrics.inc.assert_called_once_with("bot_curse_words_total", value=2)

    async def test_skips_forwarded_messages(self):
        repo = make_repository()
        repo.db.curse_words = {"мат"}
        metrics = MagicMock()
        handler = _make_handler(repo)

        ctx = make_text_context("мат", repo=repo, metrics=metrics)
        ctx.message.forward_origin = object()
        ok = await handler.chat(ctx)

        assert not ok
        metrics.inc.assert_not_called()

    async def test_skips_commands_and_punctuation(self):
        repo = make_repository()
        repo.db.curse_words = {"мат"}
        metrics = MagicMock()
        handler = _make_handler(repo)

        cmd_ctx = make_text_context("/curse word_list add мат", repo=repo, metrics=metrics)
        punct_ctx = make_text_context("мат,", repo=repo, metrics=metrics)

        await handler.chat(cmd_ctx)
        await handler.chat(punct_ctx)

        metrics.inc.assert_not_called()

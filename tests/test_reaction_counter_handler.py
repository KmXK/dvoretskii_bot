"""Tests for ReactionCounterHandler — reaction() implementation is mostly no-op."""
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import make_repository


class TestReactionCounterHandler:
    async def test_reaction_does_not_crash(self):
        from steward.handlers.reaction_counter_handler import ReactionCounterHandler

        handler = ReactionCounterHandler()
        handler.repository = make_repository()
        handler.bot = MagicMock()

        ctx = MagicMock()
        with patch(
            "steward.handlers.reaction_counter_handler.get_reactions_info",
            AsyncMock(return_value=MagicMock()),
        ):
            result = await handler.reaction(ctx)

        assert result is None

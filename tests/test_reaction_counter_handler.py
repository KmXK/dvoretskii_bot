"""Tests for ReactionCounterFeature — reaction() implementation is mostly no-op."""
from unittest.mock import AsyncMock, MagicMock, patch

from steward.features.reaction_counter import ReactionCounterFeature
from tests.conftest import make_repository


class TestReactionCounterFeature:
    async def test_reaction_does_not_crash(self):
        feature = ReactionCounterFeature()
        feature.repository = make_repository()
        feature.bot = MagicMock()

        ctx = MagicMock()
        with patch(
            "steward.features.reaction_counter.get_reactions_info",
            AsyncMock(return_value=MagicMock()),
        ):
            result = await feature.reaction(ctx)

        assert result is False or result is None

"""Passive collector: silently watches chat messages and occasionally asks a
cheap model to extract personal facts about the author. Cost-minimised by a
heuristic funnel; see steward.helpers.user_memory for details.

This feature never replies to the user and always returns False from
@on_message so it doesn't block other handlers.
"""

import asyncio
import logging

from steward.framework import Feature, FeatureContext, on_message
from steward.helpers.ai_context import get_ai_quick_handler
from steward.helpers.user_memory import (
    add_facts,
    chat_memory_collector,
    extract_facts_batch_via_ai,
)

logger = logging.getLogger(__name__)


class UserMemoryFeature(Feature):
    excluded_from_ai_router = True

    @on_message
    async def observe(self, ctx: FeatureContext) -> bool:
        if ctx.message is None or not ctx.message.text:
            return False
        if ctx.message.from_user is None or ctx.message.from_user.is_bot:
            return False

        user_id = ctx.message.from_user.id
        batch = chat_memory_collector.observe(user_id, ctx.message.text)
        if batch is None:
            return False

        quick_call = get_ai_quick_handler("ai")
        if quick_call is None:
            return False

        asyncio.create_task(
            _extract_and_persist_bg(ctx.repository, user_id, batch, quick_call)
        )
        return False


async def _extract_and_persist_bg(repository, user_id, batch, quick_call):
    try:
        facts = await extract_facts_batch_via_ai(batch, quick_call)
        if not facts:
            return
        added = add_facts(repository, user_id, facts)
        if added:
            await repository.save()
    except Exception as e:
        logger.debug("chat memory bg failed: %s", e)

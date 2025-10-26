import logging
from typing import Iterable, cast

from telegram import ReactionType, ReactionTypeCustomEmoji, ReactionTypeEmoji

from steward.bot.context import ReactionBotContext

custom_emoji_id_to_emoji_cache: dict[str, str] = {}


async def fill_emoji_cache(
    context: ReactionBotContext,
    custom_emoji_ids: list[str],
):
    global custom_emoji_id_to_emoji_cache
    need_to_fetch = [
        x for x in custom_emoji_ids if x not in custom_emoji_id_to_emoji_cache
    ]

    if len(need_to_fetch) > 0:
        for sticker in await context.bot.get_custom_emoji_stickers(
            [x for x in need_to_fetch]
        ):
            logging.info(sticker)
            assert sticker.custom_emoji_id
            assert sticker.emoji
            custom_emoji_id_to_emoji_cache[sticker.custom_emoji_id] = sticker.emoji


async def get_reactions_data(
    context: ReactionBotContext,
    reactions: Iterable[ReactionType],
):
    await fill_emoji_cache(
        context,
        [
            cast(ReactionTypeCustomEmoji, x).custom_emoji_id
            for x in reactions
            if isinstance(x, ReactionTypeCustomEmoji)
        ],
    )

    return {
        x.emoji
        if isinstance(x, ReactionTypeEmoji)
        else custom_emoji_id_to_emoji_cache[
            cast(ReactionTypeCustomEmoji, x).custom_emoji_id
        ]
        for x in reactions
    }


class ReactionsInfo:
    def __init__(self, added: set[str] = set(), removed: set[str] = set()) -> None:
        self.added = added
        self.removed = removed


async def get_reactions_info(context: ReactionBotContext) -> ReactionsInfo:
    message = context.message_reaction

    old_reactions = await get_reactions_data(context, message.old_reaction)
    new_reaction = await get_reactions_data(context, message.new_reaction)

    if old_reactions == new_reaction:
        logging.warning(message)
        return ReactionsInfo()

    deleted_reactions = old_reactions - new_reaction
    added_reactions = new_reaction - old_reactions

    return ReactionsInfo(
        added=added_reactions,
        removed=deleted_reactions,
    )

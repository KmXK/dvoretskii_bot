import logging

from steward.bot.context import ReactionBotContext
from steward.handlers.handler import Handler
from steward.helpers.reactions import get_reactions_info

logger = logging.getLogger(__name__)


class ReactionCounterHandler(Handler):
    async def reaction(self, context: ReactionBotContext):
        """
        Обрабатывает реакции на сообщения бота с видео И на сообщения пользователя со ссылкой.
        Связывает реакции с автором оригинального видео (кто кинул ссылку).
        """
        info = await get_reactions_info(context)
        
        if not (info.added or info.removed):
            return
        
        message_reaction = context.message_reaction
        chat_id = message_reaction.chat.id
        message_id = message_reaction.message_id
        user_id = message_reaction.user.id
        
        # Найти VideoReaction для этого сообщения
        # Проверяем оба варианта: сообщение бота с видео И сообщение пользователя со ссылкой
        video_reaction = None
        for vr in context.repository.db.video_reactions:
            if vr.chat_id == chat_id and (
                vr.bot_message_id == message_id or vr.user_message_id == message_id
            ):
                video_reaction = vr
                break
        
        if not video_reaction:
            # Это не связанное с видео сообщение
            logger.debug(f"No video_reaction found for message {message_id} in chat {chat_id}")
            return
        
        # Обновить счетчик реакций
        if user_id not in video_reaction.reactions:
            video_reaction.reactions[user_id] = set()
        
        # Добавить новые реакции
        for emoji in info.added:
            video_reaction.reactions[user_id].add(emoji)
        
        # Удалить убранные реакции
        for emoji in info.removed:
            video_reaction.reactions[user_id].discard(emoji)
        
        # Если юзер убрал все реакции, удалить его из списка
        if not video_reaction.reactions[user_id]:
            del video_reaction.reactions[user_id]
        
        await context.repository.save()
        
        logger.info(
            f"Updated reactions for video by user {video_reaction.user_id}: "
            f"{video_reaction.get_total_reactions()} users, "
            f"{video_reaction.get_reactions_count()} total reactions"
        )

import logging

from steward.bot.context import ReactionBotContext
from steward.handlers.handler import Handler
from steward.helpers.reactions import get_reactions_info

logger = logging.getLogger(__name__)


class ReactionCounterHandler(Handler):
    async def reaction(self, context: ReactionBotContext):
        """
        Обрабатывает реакции на сообщения бота с видео И на сообщения пользователя со ссылкой.
        Использует метрики Prometheus для подсчёта.
        """
        info = await get_reactions_info(context)
        
        if not (info.added or info.removed):
            return
        
        message_reaction = context.message_reaction
        chat_id = message_reaction.chat.id
        message_id = message_reaction.message_id
        reactor_user_id = message_reaction.user.id
        
        # Найти автора видео по bot_message_id
        key = f"{chat_id}:{message_id}"
        author_info = context.repository.db.video_message_authors.get(key)
        
        if not author_info:
            # Это не связанное с видео сообщение
            logger.debug(f"No video author mapping for message {message_id} in chat {chat_id}")
            return
        
        author_user_id, video_type = author_info
        
        # Инкрементируем метрики для добавленных реакций
        for emoji in info.added:
            context.metrics.inc(
                "video_reactions_total",
                {
                    "author_user_id": str(author_user_id),
                    "reactor_user_id": str(reactor_user_id),
                    "chat_id": str(chat_id),
                    "video_type": video_type,
                    "emoji": emoji,
                },
            )
            logger.info(
                f"Reaction added: user {reactor_user_id} -> {emoji} on video by {author_user_id} ({video_type})"
            )
        
        # Декрементируем метрики для удалённых реакций (если нужно)
        # Примечание: Counter в Prometheus не поддерживает декремент,
        # но можно игнорировать удаления или использовать Gauge
        for emoji in info.removed:
            logger.info(
                f"Reaction removed: user {reactor_user_id} -> {emoji} on video by {author_user_id} ({video_type})"
            )

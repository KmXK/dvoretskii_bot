import logging
from collections import defaultdict

from steward.handlers.handler import Handler

logger = logging.getLogger(__name__)


class VideoStatsHandler(Handler):
    """
    Показывает статистику по реакциям на видео пользователей.
    Команда: /video_stats или /reactions_top
    """

    async def chat(self, context):
        message = context.message
        
        if not message.text:
            return False
        
        text = message.text.strip()
        
        if text not in ["/video_stats", "/reactions_top", "/video_stats@dvoretskii_bot", "/reactions_top@dvoretskii_bot"]:
            return False
        
        # Подсчитать статистику по пользователям
        user_stats = defaultdict(lambda: {"videos": 0, "total_reactions": 0, "total_users": 0})
        
        for vr in context.repository.db.video_reactions:
            if vr.chat_id != message.chat_id:
                continue
            
            user_stats[vr.user_id]["videos"] += 1
            user_stats[vr.user_id]["total_reactions"] += vr.get_reactions_count()
            user_stats[vr.user_id]["total_users"] += vr.get_total_reactions()
        
        if not user_stats:
            await message.reply_text("📊 Статистика пока пуста. Отправьте видео и получите реакции!")
            return True
        
        # Сортировка по количеству уникальных пользователей, поставивших реакцию
        sorted_users = sorted(
            user_stats.items(),
            key=lambda x: (x[1]["total_users"], x[1]["total_reactions"]),
            reverse=True,
        )
        
        # Формирование ответа
        reply_text = "📊 <b>Топ по реакциям на видео:</b>\n\n"
        
        for idx, (user_id, stats) in enumerate(sorted_users[:10], start=1):
            try:
                user = await context.bot.get_chat_member(message.chat_id, user_id)
                username = user.user.first_name or f"User {user_id}"
            except Exception as e:
                logger.exception(e)
                username = f"User {user_id}"
            
            medal = ""
            if idx == 1:
                medal = "🥇 "
            elif idx == 2:
                medal = "🥈 "
            elif idx == 3:
                medal = "🥉 "
            
            reply_text += (
                f"{medal}<b>{idx}.</b> {username}\n"
                f"   ├ Видео: {stats['videos']}\n"
                f"   ├ Уникальных пользователей: {stats['total_users']}\n"
                f"   └ Всего реакций: {stats['total_reactions']}\n\n"
            )
        
        await message.reply_text(reply_text, parse_mode="HTML")
        return True

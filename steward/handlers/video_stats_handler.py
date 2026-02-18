import logging
from collections import defaultdict

from steward.handlers.handler import Handler

logger = logging.getLogger(__name__)


class VideoStatsHandler(Handler):
    """
    Показывает статистику по реакциям на видео пользователей.
    Читает данные из метрик Prometheus/VictoriaMetrics.
    Команда: /video_stats или /reactions_top
    """

    async def chat(self, context):
        message = context.message
        
        if not message.text:
            return False
        
        text = message.text.strip()
        
        if text not in ["/video_stats", "/reactions_top", "/video_stats@dvoretskii_bot", "/reactions_top@dvoretskii_bot"]:
            return False
        
        chat_id = str(message.chat_id)
        
        # Запрос метрик из VictoriaMetrics/Prometheus
        # Считаем уникальных пользователей (reactor_user_id) по каждому автору
        query_unique_users = f'count by (author_user_id) (video_reactions_total{{chat_id="{chat_id}"}})'
        # Считаем общее количество реакций
        query_total_reactions = f'sum by (author_user_id) (video_reactions_total{{chat_id="{chat_id}"}})'
        
        try:
            unique_users_data = await context.metrics.query(query_unique_users)
            total_reactions_data = await context.metrics.query(query_total_reactions)
        except Exception as e:
            logger.exception(e)
            await message.reply_text(
                "⚠️ Не удалось получить статистику из метрик.\n"
                "Убедитесь, что VictoriaMetrics настроена и доступна."
            )
            return True
        
        # Объединить данные
        user_stats = defaultdict(lambda: {"total_users": 0, "total_reactions": 0})
        
        for sample in unique_users_data:
            author_id = int(sample.labels.get("author_user_id", 0))
            user_stats[author_id]["total_users"] = int(sample.value)
        
        for sample in total_reactions_data:
            author_id = int(sample.labels.get("author_user_id", 0))
            user_stats[author_id]["total_reactions"] = int(sample.value)
        
        if not user_stats:
            await message.reply_text("📊 Статистика пока пуста. Отправьте видео и получите реакции!")
            return True
        
        # Сортировка по количеству уникальных пользователей
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
                f"   ├ Уникальных пользователей: {stats['total_users']}\n"
                f"   └ Всего реакций: {stats['total_reactions']}\n\n"
            )
        
        await message.reply_text(reply_text, parse_mode="HTML")
        return True

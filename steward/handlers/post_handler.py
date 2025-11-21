from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from steward.bot.context import ChatBotContext
from steward.delayed_action.post import (
    CHANNEL_ID,
    PostDelayedAction,
    SingleTimeGenerator,
)
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler

TIMEZONE = ZoneInfo("Europe/Minsk")


def parse_time(time_str: str) -> time | None:
    """Парсит время в формате HH:MM"""
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour=hour, minute=minute)
        return None
    except (ValueError, IndexError):
        return None


@CommandHandler(
    "post",
    arguments_template=r"(?P<time_str>\d{1,2}:\d{2})?",
)
class PostHandler(Handler):
    async def chat(
        self,
        context: ChatBotContext,
        time_str: str | None = None,
    ):
        chat_id = context.message.chat_id
        now = datetime.now(TIMEZONE)

        # Определяем время выполнения
        if time_str:
            # Если указано время, парсим его
            parsed_time = parse_time(time_str)
            if parsed_time is None:
                await context.message.reply_text(
                    "Неверный формат времени. Используйте формат HH:MM (например, 16:00)"
                )
                return True

            # Создаем datetime для указанного времени сегодня или завтра
            target_datetime = datetime.combine(now.date(), parsed_time).replace(
                tzinfo=TIMEZONE
            )

            # Если время уже прошло сегодня, планируем на завтра
            if target_datetime <= now:
                target_datetime = target_datetime + timedelta(days=1)
        else:
            # Если время не указано, отправляем через несколько секунд
            target_datetime = now + timedelta(seconds=2)

        # Создаем отложенное действие
        delayed_action = PostDelayedAction(
            chat_id=chat_id,
            channel_id=CHANNEL_ID,
            generator=SingleTimeGenerator(target_time=target_datetime),
        )

        self.repository.db.delayed_actions.append(delayed_action)
        await self.repository.save()

        if time_str:
            await context.message.reply_text(
                f"Пост будет отправлен в {target_datetime.strftime('%H:%M')} "
                f"({target_datetime.strftime('%d.%m.%Y')})"
            )
        else:
            await context.message.reply_text(
                "Пост будет отправлен через несколько секунд"
            )

        return True

    def help(self) -> str | None:
        return "/post [HH:MM] - переслать последний пост из канала (с опциональным временем отправки)"

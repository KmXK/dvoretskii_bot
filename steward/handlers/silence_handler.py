import logging
import re
from datetime import datetime, timedelta, timezone

from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler

logger = logging.getLogger(__name__)


def _parse_duration(raw: str) -> timedelta | None:
    if raw.isdigit():
        return timedelta(minutes=int(raw))

    duration_pattern = re.compile(r"(?P<value>\d+)\s*(?P<unit>[smhd])", re.IGNORECASE)
    total_seconds = 0

    for match in duration_pattern.finditer(raw):
        value = int(match.group("value"))
        unit = match.group("unit").lower()

        if unit == "s":
            total_seconds += value
        elif unit == "m":
            total_seconds += value * 60
        elif unit == "h":
            total_seconds += value * 3600
        elif unit == "d":
            total_seconds += value * 86400

    if total_seconds == 0:
        return None

    return timedelta(seconds=total_seconds)


def _format_timedelta(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    parts: list[str] = []

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if seconds and not parts:
        parts.append(f"{seconds}с")

    return " ".join(parts) if parts else "несколько секунд"


@CommandHandler(
    "silence",
    only_admin=True,
    arguments_template=r"(?P<duration>.+)?",
)
class SilenceCommandHandler(Handler):
    async def chat(self, context: ChatBotContext, duration: str | None = None):
        chat_id = context.message.chat_id

        if duration is None or duration.strip().lower() in {
            "off",
            "stop",
            "cancel",
            "0",
        }:
            if self.repository.db.silenced_chats.pop(chat_id, None) is not None:
                await self.repository.save()
                await context.message.reply_text("Режим тишины отключен")
            else:
                await context.message.reply_text("Режим тишины уже отключён")
            return True

        duration_arg = duration.strip().lower()
        delta = _parse_duration(duration_arg)

        if delta is None:
            await context.message.reply_text(
                "Не получилось распознать время. Используй формат вида 10m, 2h30m, 45s."
            )
            return True

        expires_at = datetime.now(timezone.utc) + delta
        self.repository.db.silenced_chats[chat_id] = expires_at
        await self.repository.save()

        await context.message.reply_text(
            f"Режим тишины включен на {_format_timedelta(delta)}. "
            "Все новые сообщения будут удаляться."
        )
        return True

    def help(self):
        return "/silence [<время>|off] - включить/выключить режим тишины"


class SilenceEnforcerHandler(Handler):
    async def chat(self, context: ChatBotContext):
        chat_id = context.message.chat_id
        expires_at = self.repository.db.silenced_chats.get(chat_id)

        if expires_at is None:
            return False

        now = datetime.now(timezone.utc)
        if expires_at <= now:
            self.repository.db.silenced_chats.pop(chat_id, None)
            await self.repository.save()
            return False

        try:
            await context.message.delete()
        except BaseException as error:
            logger.warning("Failed to delete message in silence mode: %s", error)
            return False

        return True

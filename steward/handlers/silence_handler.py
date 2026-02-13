import logging
from datetime import datetime, timezone

from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.duration import format_timedelta, parse_duration

logger = logging.getLogger(__name__)


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
        delta = parse_duration(duration_arg)

        if delta is None:
            await context.message.reply_text(
                "Не получилось распознать время. Используй формат вида 10m, 2h30m, 45s."
            )
            return True

        expires_at = datetime.now(timezone.utc) + delta
        self.repository.db.silenced_chats[chat_id] = expires_at
        await self.repository.save()

        await context.message.reply_text(
            f"Режим тишины включен на {format_timedelta(delta)}. "
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

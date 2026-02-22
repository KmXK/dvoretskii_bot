import logging
from datetime import datetime, timezone

from steward.bot.context import ChatBotContext
from steward.data.models.banned_user import BannedUser
from steward.data.models.user import User
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.duration import format_timedelta, parse_duration

logger = logging.getLogger(__name__)


@CommandHandler(
    "ban",
    arguments_template=r"(?P<args>.+)?",
)
class BanCommandHandler(Handler):
    async def chat(self, context: ChatBotContext, args: str | None = None):
        chat_id = context.message.chat_id

        if self._is_sender_banned(context, chat_id):
            return False

        if args is None:
            await context.message.reply_text(
                "Формат: /ban <user> <время> или /ban stop [user]"
            )
            return True

        parts = args.strip().split()

        if parts[0].lower() in {"off", "stop", "cancel"}:
            return await self._handle_stop(context, chat_id, parts[1:])

        if len(parts) < 2:
            await context.message.reply_text("Формат: /ban <user> <время>")
            return True

        identifier = parts[0]
        duration_raw = " ".join(parts[1:])

        user = self._resolve_user(identifier)
        if user is None:
            await context.message.reply_text(f"Пользователь {identifier} не найден")
            return True

        delta = parse_duration(duration_raw)
        if delta is None:
            await context.message.reply_text(
                "Не получилось распознать время. Используй формат вида 10m, 2h30m, 45s."
            )
            return True

        expires_at = datetime.now(timezone.utc) + delta

        self.repository.db.banned_users = [
            b
            for b in self.repository.db.banned_users
            if not (b.chat_id == chat_id and b.user_id == user.id)
        ]
        self.repository.db.banned_users.append(
            BannedUser(chat_id=chat_id, user_id=user.id, expires_at=expires_at)
        )
        await self.repository.save()

        display = f"@{user.username}" if user.username else str(user.id)
        await context.message.reply_text(
            f"Бан для {display} включен на {format_timedelta(delta)}. "
            "Сообщения будут удаляться."
        )
        return True

    async def _handle_stop(
        self, context: ChatBotContext, chat_id: int, extra: list[str]
    ):
        sender_id = context.message.from_user.id if context.message.from_user else None

        if extra:
            user = self._resolve_user(extra[0])
            if user is None:
                await context.message.reply_text(f"Пользователь {extra[0]} не найден")
                return True

            if user.id == sender_id:
                return True

            before = len(self.repository.db.banned_users)
            self.repository.db.banned_users = [
                b
                for b in self.repository.db.banned_users
                if not (b.chat_id == chat_id and b.user_id == user.id)
            ]
            if len(self.repository.db.banned_users) < before:
                await self.repository.save()
                display = f"@{user.username}" if user.username else str(user.id)
                await context.message.reply_text(f"Бан для {display} снят")
            else:
                await context.message.reply_text("Этот пользователь не забанен")
            return True

        before = len(self.repository.db.banned_users)
        self.repository.db.banned_users = [
            b
            for b in self.repository.db.banned_users
            if b.chat_id != chat_id or b.user_id == sender_id
        ]
        if len(self.repository.db.banned_users) < before:
            await self.repository.save()
            await context.message.reply_text("Все баны в этом чате сняты")
        else:
            await context.message.reply_text("Нет активных банов")
        return True

    def _is_sender_banned(self, context: ChatBotContext, chat_id: int) -> bool:
        sender_id = (
            context.message.from_user.id if context.message.from_user else None
        )
        return any(
            b.chat_id == chat_id and b.user_id == sender_id
            for b in self.repository.db.banned_users
        )

    def _resolve_user(self, identifier: str) -> User | None:
        identifier = identifier.lstrip("@")
        try:
            user_id = int(identifier)
            return next((u for u in self.repository.db.users if u.id == user_id), None)
        except ValueError:
            pass
        return next(
            (
                u
                for u in self.repository.db.users
                if u.username and u.username.lower() == identifier.lower()
            ),
            None,
        )

    def help(self):
        return "/ban <user> <время> — бан пользователя (удаление сообщений)"

    def prompt(self):
        return (
            "▶ /ban — бан пользователя\n"
            "  Синтаксис: /ban <user> <время>\n"
            "  Примеры:\n"
            "  - «забань @user на 2 часа» → /ban @user 2h"
        )


class BanEnforcerHandler(Handler):
    async def chat(self, context: ChatBotContext):
        chat_id = context.message.chat_id
        user_id = context.message.from_user.id if context.message.from_user else None

        if user_id is None:
            return False

        ban = next(
            (
                b
                for b in self.repository.db.banned_users
                if b.chat_id == chat_id and b.user_id == user_id
            ),
            None,
        )

        if ban is None:
            return False

        now = datetime.now(timezone.utc)
        if ban.expires_at <= now:
            self.repository.db.banned_users.remove(ban)
            await self.repository.save()
            return False

        try:
            await context.message.delete()
        except BaseException as error:
            logger.warning("Failed to delete message in ban mode: %s", error)
            return False

        return True

import logging

from steward.bot.context import ChatBotContext
from steward.data.models.forward_mute import ForwardMute
from steward.data.models.user import User
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler

logger = logging.getLogger(__name__)


@CommandHandler(
    "mute_forwards",
    arguments_template=r"(?P<args>.+)?",
)
class MuteForwardsCommandHandler(Handler):
    async def chat(self, context: ChatBotContext, args: str | None = None):
        chat_id = context.message.chat_id
        sender_id = (
            context.message.from_user.id if context.message.from_user else None
        )

        if args is None:
            await context.message.reply_text(
                "Формат: /mute_forwards <user> или /mute_forwards stop [user]"
            )
            return True

        parts = args.strip().split()

        if parts[0].lower() in {"off", "stop", "cancel"}:
            if self._is_sender_banned(chat_id, sender_id) and not self.repository.is_admin(sender_id):
                return False
            return await self._handle_stop(context, chat_id, parts[1:])

        identifier = parts[0]
        user = self._resolve_user(identifier)
        if user is None:
            await context.message.reply_text(f"Пользователь {identifier} не найден")
            return True

        already = any(
            m.chat_id == chat_id and m.user_id == user.id
            for m in self.repository.db.forward_mutes
        )
        if already:
            display = f"@{user.username}" if user.username else str(user.id)
            await context.message.reply_text(
                f"Пересылки от {display} уже блокируются"
            )
            return True

        self.repository.db.forward_mutes.append(
            ForwardMute(chat_id=chat_id, user_id=user.id)
        )
        await self.repository.save()

        display = f"@{user.username}" if user.username else str(user.id)
        await context.message.reply_text(
            f"Пересланные посты от {display} будут удаляться"
        )
        return True

    async def _handle_stop(
        self, context: ChatBotContext, chat_id: int, extra: list[str]
    ):
        if extra:
            user = self._resolve_user(extra[0])
            if user is None:
                await context.message.reply_text(f"Пользователь {extra[0]} не найден")
                return True

            before = len(self.repository.db.forward_mutes)
            self.repository.db.forward_mutes = [
                m
                for m in self.repository.db.forward_mutes
                if not (m.chat_id == chat_id and m.user_id == user.id)
            ]
            if len(self.repository.db.forward_mutes) < before:
                await self.repository.save()
                display = f"@{user.username}" if user.username else str(user.id)
                await context.message.reply_text(
                    f"Блокировка пересылок для {display} снята"
                )
            else:
                await context.message.reply_text(
                    "У этого пользователя нет блокировки пересылок"
                )
            return True

        before = len(self.repository.db.forward_mutes)
        self.repository.db.forward_mutes = [
            m for m in self.repository.db.forward_mutes if m.chat_id != chat_id
        ]
        if len(self.repository.db.forward_mutes) < before:
            await self.repository.save()
            await context.message.reply_text(
                "Все блокировки пересылок в этом чате сняты"
            )
        else:
            await context.message.reply_text("Нет активных блокировок пересылок")
        return True

    def _is_sender_banned(self, chat_id: int, sender_id: int | None) -> bool:
        if sender_id is None:
            return False
        return any(
            b.chat_id == chat_id and b.user_id == sender_id
            for b in self.repository.db.banned_users
        )

    def _resolve_user(self, identifier: str) -> User | None:
        identifier = identifier.lstrip("@")
        try:
            user_id = int(identifier)
            return next(
                (u for u in self.repository.db.users if u.id == user_id), None
            )
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
        return (
            "/mute_forwards <user> — блокировать пересланные посты от пользователя; "
            "/mute_forwards stop [user] — снять блокировку"
        )

    def prompt(self):
        return (
            "▶ /mute_forwards — блокировка пересланных постов от пользователя\n"
            "  Синтаксис: /mute_forwards <user> | /mute_forwards stop [user]\n"
            "  Примеры:\n"
            "  - «блокируй репосты от @user» → /mute_forwards @user\n"
            "  - «сними блокировку пересылок с @user» → /mute_forwards stop @user\n"
            "  - «разреши все пересылки» → /mute_forwards stop"
        )


class MuteForwardsEnforcerHandler(Handler):
    async def chat(self, context: ChatBotContext):
        message = context.message

        is_forward = getattr(message, "forward_origin", None) is not None
        has_media = bool(getattr(message, "photo", None)) or getattr(
            message, "video", None
        ) is not None
        is_media_post = has_media

        if not (is_forward or is_media_post):
            return False

        chat_id = message.chat_id
        user_id = message.from_user.id if message.from_user else None
        if user_id is None:
            return False

        muted = any(
            m.chat_id == chat_id and m.user_id == user_id
            for m in self.repository.db.forward_mutes
        )
        if not muted:
            return False

        try:
            await context.message.delete()
        except BaseException as error:
            logger.warning("Failed to delete forwarded message: %s", error)
            return False

        return True

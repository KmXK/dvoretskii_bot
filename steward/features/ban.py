import logging
from datetime import datetime, timezone

from steward.data.models.banned_user import BannedUser
from steward.data.models.user import User
from steward.framework import (
    Feature,
    FeatureContext,
    collection,
    on_message,
    subcommand,
)
from steward.helpers.duration import format_timedelta, parse_duration

logger = logging.getLogger(__name__)


class BanFeature(Feature):
    command = "ban"
    description = "Бан пользователя (удаление сообщений)"
    help_examples = ["«забань @user на 2 часа» → /ban @user 2h"]

    banned = collection("banned_users")
    users = collection("users")

    @subcommand("", description="Подсказка по использованию")
    async def usage(self, ctx: FeatureContext):
        await ctx.reply("Формат: /ban <user> <время> или /ban stop [user]")

    @subcommand("stop", description="Снять все баны в чате")
    async def stop_all(self, ctx: FeatureContext):
        chat_id = ctx.chat_id
        sender_id = ctx.user_id
        before = len(self.banned.all())
        keep = [b for b in self.banned if b.chat_id != chat_id or b.user_id == sender_id]
        if len(keep) == before:
            await ctx.reply("Нет активных банов")
            return
        self.banned.replace_all(keep)
        await self.banned.save()
        await ctx.reply("Все баны в этом чате сняты")

    @subcommand("stop <identifier:str>", description="Снять бан с пользователя")
    async def stop_one(self, ctx: FeatureContext, identifier: str):
        chat_id = ctx.chat_id
        sender_id = ctx.user_id
        user = self._resolve_user(identifier)
        if user is None:
            await ctx.reply(f"Пользователь {identifier} не найден")
            return
        if user.id == sender_id:
            return
        before = len(self.banned.all())
        keep = [b for b in self.banned if not (b.chat_id == chat_id and b.user_id == user.id)]
        if len(keep) == before:
            await ctx.reply("Этот пользователь не забанен")
            return
        self.banned.replace_all(keep)
        await self.banned.save()
        display = f"@{user.username}" if user.username else str(user.id)
        await ctx.reply(f"Бан для {display} снят")

    @subcommand("<identifier:str> <duration:rest>", description="Забанить пользователя")
    async def ban(self, ctx: FeatureContext, identifier: str, duration: str):
        chat_id = ctx.chat_id
        if self._is_sender_banned(chat_id, ctx.user_id):
            return False

        user = self._resolve_user(identifier)
        if user is None:
            await ctx.reply(f"Пользователь {identifier} не найден")
            return
        delta = parse_duration(duration)
        if delta is None:
            await ctx.reply("Не получилось распознать время. Используй формат вида 10m, 2h30m, 45s.")
            return
        expires_at = datetime.now(timezone.utc) + delta
        keep = [b for b in self.banned if not (b.chat_id == chat_id and b.user_id == user.id)]
        keep.append(BannedUser(chat_id=chat_id, user_id=user.id, expires_at=expires_at))
        self.banned.replace_all(keep)
        await self.banned.save()
        display = f"@{user.username}" if user.username else str(user.id)
        await ctx.reply(
            f"Бан для {display} включен на {format_timedelta(delta)}. Сообщения будут удаляться."
        )

    def _resolve_user(self, identifier: str) -> User | None:
        identifier = identifier.lstrip("@")
        try:
            return self.users.find_by(id=int(identifier))
        except ValueError:
            pass
        return self.users.find_one(
            lambda u: u.username and u.username.lower() == identifier.lower()
        )

    def _is_sender_banned(self, chat_id: int, user_id: int) -> bool:
        return any(b.chat_id == chat_id and b.user_id == user_id for b in self.banned)


class BanEnforcerFeature(Feature):
    banned = collection("banned_users")

    @on_message
    async def enforce(self, ctx: FeatureContext) -> bool | None:
        if ctx.message is None or ctx.message.from_user is None:
            return False
        chat_id = ctx.chat_id
        user_id = ctx.user_id
        ban = next(
            (b for b in self.banned if b.chat_id == chat_id and b.user_id == user_id),
            None,
        )
        if ban is None:
            return False
        if ban.expires_at <= datetime.now(timezone.utc):
            self.banned.remove(ban)
            await self.banned.save()
            return False
        try:
            await ctx.message.delete()
        except BaseException as error:
            logger.warning("Failed to delete message in ban mode: %s", error)
            return False
        return True

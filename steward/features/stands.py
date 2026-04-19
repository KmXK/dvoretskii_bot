from dataclasses import dataclass

from steward.framework import (
    Feature,
    FeatureContext,
    collection,
    on_message,
    subcommand,
)
from steward.helpers.command_validation import ValidationArgumentsError


@dataclass
class _PendingStandAdd:
    stand_name: str
    description: str | None = None
    step: str = "description"


class StandsFeature(Feature):
    command = "stands"
    description = "Пользователи (stands)"
    help_examples = [
        "«покажи всех пользователей» → /stands",
        "«добавь пользователя Star Platinum» → /stands add Star Platinum",
        "«удали пользователя Star Platinum» → /stands remove Star Platinum",
    ]

    users = collection("users")

    def __init__(self):
        super().__init__()
        self._pending_add: dict[int, _PendingStandAdd] = {}

    @subcommand("", description="Список")
    async def view(self, ctx: FeatureContext):
        await ctx.reply(self._build_list())

    @subcommand("add <name:rest>", description="Добавить пользователя")
    async def add(self, ctx: FeatureContext, name: str):
        stand_name = name.strip()
        if not stand_name:
            raise ValidationArgumentsError()
        existing = self._by_stand(stand_name)
        if existing is not None:
            await ctx.reply(
                f"Пользователь «{stand_name}» уже привязан к @{existing.username or existing.id}"
            )
            return
        self._pending_add[ctx.user_id] = _PendingStandAdd(stand_name=stand_name)
        await ctx.reply(
            f"Добавляем пользователя «{stand_name}».\n"
            "Пришли описание пользователя одним сообщением."
        )

    @subcommand("remove <name:rest>", description="Удалить пользователя")
    async def remove(self, ctx: FeatureContext, name: str):
        stand_name = name.strip()
        if not stand_name:
            raise ValidationArgumentsError()
        user = self._by_stand(stand_name)
        if user is None:
            await ctx.reply(f"Пользователь «{stand_name}» не найден.")
            return
        user.stand_name = None
        user.stand_description = None
        await self.users.save()
        await ctx.reply(f"Пользователь «{stand_name}» удален.")

    @on_message
    async def handle_pending(self, ctx: FeatureContext) -> bool:
        if ctx.message is None:
            return False
        text = ctx.message.text or ""
        if text.startswith("/"):
            return False
        pending = self._pending_add.get(ctx.user_id)
        if pending is None:
            return False
        trimmed = text.strip()
        if not trimmed:
            await ctx.reply("Сообщение пустое, пришли текст.")
            return True

        if pending.step == "description":
            pending.description = trimmed
            pending.step = "user"
            await ctx.reply("Теперь укажи владельца (@username или user_id).")
            return True

        target = self._by_identifier(trimmed)
        if target is None:
            await ctx.reply("Пользователь не найден. Укажи @username или user_id.")
            return True

        assert pending.description is not None
        if target.stand_name and target.stand_name.strip():
            await ctx.reply(
                f"У @{target.username or target.id} уже есть пользователь «{target.stand_name}»."
            )
            self._pending_add.pop(ctx.user_id, None)
            return True

        same = self._by_stand(pending.stand_name)
        if same is not None and same.id != target.id:
            await ctx.reply(f"Пользователь «{pending.stand_name}» уже привязан к другому владельцу.")
            self._pending_add.pop(ctx.user_id, None)
            return True

        target.stand_name = pending.stand_name
        target.stand_description = pending.description
        await self.users.save()
        self._pending_add.pop(ctx.user_id, None)
        await ctx.reply(
            f"Готово. Пользователь «{target.stand_name}» сохранен для @{target.username or target.id}."
        )
        return True

    def _build_list(self) -> str:
        items = []
        for user in self.users:
            if not user.stand_name or not user.stand_description:
                continue
            owner = f"@{user.username}" if user.username else str(user.id)
            items.append(
                (user.stand_name.strip(), user.stand_description.strip(), owner)
            )
        if not items:
            return "Пользователей пока нет."
        items.sort(key=lambda x: x[0].lower())
        lines = ["Пользователи:"]
        for name, description, owner in items:
            lines.append(f"- {name}: {description} ({owner})")
        return "\n".join(lines)

    def _by_stand(self, stand_name: str):
        target = stand_name.strip().lower()
        return self.users.find_one(
            lambda u: u.stand_name and u.stand_name.strip().lower() == target
        )

    def _by_identifier(self, identifier: str):
        value = identifier.strip().lstrip("@")
        if not value:
            return None
        if value.isdigit():
            return self.users.find_by(id=int(value))
        target = value.lower()
        return self.users.find_one(
            lambda u: u.username and u.username.lower() == target
        )

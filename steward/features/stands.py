import asyncio
import logging

from steward.framework import (
    Feature,
    FeatureContext,
    ask,
    collection,
    subcommand,
    wizard,
)
from steward.helpers.command_validation import ValidationArgumentsError
from steward.helpers.validation import Error, validate_message_text

logger = logging.getLogger(__name__)


def _strip_nonempty(value: str):
    value = value.strip()
    return value or Error("Сообщение пустое, пришли текст.")


def _parse_owner_identifier(value: str, state: dict):
    key = value.strip().lstrip("@").lower()
    target_user_id = state["_owner_ids"].get(key)
    if target_user_id is None:
        return Error("Пользователь не найден. Укажи @username или user_id.")
    return target_user_id


class StandsFeature(Feature):
    command = "stands"
    description = "Пользователи (stands)"
    help_examples = [
        "«покажи всех пользователей» → /stands",
        "«добавь пользователя Star Platinum» → /stands add Star Platinum",
        "«удали пользователя Star Platinum» → /stands remove Star Platinum",
    ]

    users = collection("users")

    @subcommand("", description="Список")
    async def view(self, ctx: FeatureContext):
        await ctx.reply(self._build_list(ctx.chat_id))

    @subcommand("add <name:rest>", description="Добавить пользователя")
    async def add(self, ctx: FeatureContext, name: str):
        stand_name = name.strip()
        if not stand_name:
            raise ValidationArgumentsError()
        existing = self._by_stand(stand_name)
        if existing is not None:
            await ctx.reply(
                f"Пользователь «{stand_name}» уже привязан к "
                f"@{existing.username or existing.id}"
            )
            return
        owner_ids: dict[str, int] = {}
        for user in self.users:
            if ctx.chat_id not in (user.chat_ids or []):
                continue
            owner_ids[str(user.id)] = user.id
            if user.username:
                owner_ids[user.username.lower()] = user.id
        await self.start_wizard(
            "stands:add",
            ctx,
            stand_name=stand_name,
            _owner_ids=owner_ids,
        )

    @subcommand("remove <name:rest>", description="Удалить пользователя")
    async def remove(self, ctx: FeatureContext, name: str):
        stand_name = name.strip()
        if not stand_name:
            raise ValidationArgumentsError()
        user = self._visible_by_stand(ctx.chat_id, stand_name)
        if user is None:
            await ctx.reply(f"Пользователь «{stand_name}» не найден.")
            return
        user.stand_name = None
        user.stand_description = None
        user.stand_aliases = []
        await self.users.save()
        await ctx.reply(f"Пользователь «{stand_name}» удален.")

    @wizard(
        "stands:add",
        ask(
            "description",
            lambda state: (
                f"Добавляем пользователя «{state['stand_name']}».\n"
                "Пришли описание пользователя одним сообщением."
            ),
            validator=validate_message_text([_strip_nonempty]),
            force_reply=True,
        ),
        ask(
            "target_user_id",
            "Теперь укажи владельца (@username или user_id).",
            validator=validate_message_text([_parse_owner_identifier]),
            force_reply=True,
        ),
    )
    async def add_done(
        self,
        ctx: FeatureContext,
        stand_name: str,
        description: str,
        target_user_id: int,
        **_,
    ):
        target = self.users.find_by(id=target_user_id)
        if target is None:
            await ctx.reply("Пользователь больше не найден. Запусти добавление заново.")
            return

        if target.stand_name and target.stand_name.strip():
            await ctx.reply(
                f"У @{target.username or target.id} уже есть пользователь «{target.stand_name}»."
            )
            return

        same = self._by_stand(stand_name)
        if same is not None and same.id != target.id:
            await ctx.reply(f"Пользователь «{stand_name}» уже привязан к другому владельцу.")
            return

        target.stand_name = stand_name
        target.stand_description = description
        target.stand_aliases = []
        await self.users.save()
        await ctx.reply(
            f"Готово. Пользователь «{target.stand_name}» сохранен для "
            f"@{target.username or target.id}."
        )
        asyncio.create_task(
            self._extract_aliases(target.id, stand_name, description)
        )

    async def _extract_aliases(
        self, user_id: int, stand_name: str, description: str
    ) -> None:
        try:
            from steward.helpers.ai import YandexModelTypes, make_yandex_ai_query
            response = await make_yandex_ai_query(
                user_id=f"stands_aliases_{user_id}",
                messages=[("user", f"Имя: {stand_name}\nОписание: {description}")],
                system_prompt=(
                    "Извлеки из описания человека все имена, прозвища и кличики. "
                    "Верни только список через запятую без пояснений. "
                    "Если имён нет — верни пустую строку."
                ),
                model=YandexModelTypes.YANDEXGPT_5_PRO,
            )
            aliases = [
                a.strip()
                for a in response.split(",")
                if a.strip() and a.strip().lower() != stand_name.lower()
            ]
            user = self.users.find_by(id=user_id)
            if user and aliases:
                user.stand_aliases = aliases
                await self.users.save()
                logger.info(
                    "Extracted %d aliases for %s: %s", len(aliases), stand_name, aliases
                )
        except Exception as e:
            logger.warning("Failed to extract aliases for user %d: %s", user_id, e)

    def _build_list(self, chat_id: int) -> str:
        items = []
        for user in self.users:
            if chat_id not in (user.chat_ids or []):
                continue
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
            lambda user: user.stand_name
            and user.stand_name.strip().lower() == target
        )

    def _visible_by_stand(self, chat_id: int, stand_name: str):
        user = self._by_stand(stand_name)
        if user is None or chat_id not in (user.chat_ids or []):
            return None
        return user

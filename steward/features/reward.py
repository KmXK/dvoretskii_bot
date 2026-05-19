import html as html_module
import re

from telegram import MessageEntity

from steward.data.models.reward import Reward
from steward.dynamic_rewards import (
    get_dynamic_reward_holder,
    get_holder_display_name,
)
from steward.framework import (
    Feature,
    FeatureContext,
    ask,
    collection,
    paginated,
    subcommand,
    wizard,
)
from steward.helpers.emoji import (
    extract_emoji,
    format_lined_list_html,
    format_reward_html,
)
from steward.helpers.tg_update_helpers import get_message
from steward.helpers.validation import validate_message_text


def _parse_inline_emoji(msg, text: str):
    if msg.entities:
        for entity in msg.entities:
            if entity.type == MessageEntity.CUSTOM_EMOJI:
                emoji_text = msg.parse_entity(entity)
                name = text.replace(emoji_text, "", 1).strip()
                if name:
                    return {
                        "name": name,
                        "emoji_text": emoji_text,
                        "custom_emoji_id": entity.custom_emoji_id,
                    }
    words = text.rsplit(maxsplit=1)
    if len(words) == 2:
        name_part, emoji_part = words
        if not re.search(r"[a-zA-Zа-яА-ЯёЁ0-9]", emoji_part) and name_part.strip():
            return {
                "name": name_part.strip(),
                "emoji_text": emoji_part,
                "custom_emoji_id": None,
            }
    return None


class RewardFeature(Feature):
    command = "rewards"
    description = "Управление достижениями"
    help_examples = [
        "«покажи достижения» → /rewards",
        "«удали достижение 5» → /rewards remove 5",
        "«вручи достижение 3 пользователю @user» → /rewards 3 present @user",
    ]

    rewards = collection("rewards")
    users = collection("users")

    @subcommand("", description="Список достижений")
    async def list_(self, ctx: FeatureContext):
        await self.paginate(ctx, "rewards")

    @subcommand("list", description="Список")
    async def list_alias(self, ctx: FeatureContext):
        await self.paginate(ctx, "rewards")

    @subcommand("add", description="Добавить (сессия)")
    async def add(self, ctx: FeatureContext):
        await self.start_wizard("rewards:add", ctx)

    @subcommand("add <args:rest>", description="Добавить inline: имя эмодзи")
    async def add_inline(self, ctx: FeatureContext, args: str):
        if ctx.message is None:
            return
        data = _parse_inline_emoji(ctx.message, args)
        if not data:
            await self.start_wizard("rewards:add", ctx)
            return
        reward = self.rewards.add(Reward(
            id=0,
            name=data["name"],
            emoji=data["emoji_text"],
            custom_emoji_id=data["custom_emoji_id"],
        ))
        await self.rewards.save()
        await ctx.reply(
            f"Достижение добавлено: {format_reward_html(reward)} (id: {reward.id})",
            html=True, markdown=False,
        )

    @subcommand("remove <id:int>", description="Удалить", admin=True)
    async def remove(self, ctx: FeatureContext, id: int):
        reward = self.rewards.find_by(id=id)
        if reward is None:
            await ctx.reply("Достижение не найдено")
            return
        if reward.dynamic_key:
            await ctx.reply("Динамическое достижение нельзя удалить")
            return
        self.rewards.remove(reward)
        for user in self.users:
            if id in user.reward_ids:
                user.reward_ids.remove(id)
        await self.rewards.save()
        await ctx.reply(
            f"Достижение {format_reward_html(reward)} удалено",
            html=True, markdown=False,
        )

    @subcommand("<reward_id:int> present <users:rest>", description="Вручить")
    async def present(self, ctx: FeatureContext, reward_id: int, users: str):
        reward = self.rewards.find_by(id=reward_id)
        if reward is None:
            await ctx.reply("Достижение не найдено")
            return
        if reward.dynamic_key:
            await ctx.reply("Динамическое достижение нельзя вручить вручную")
            return
        resolved, errors = [], []
        for identifier in users.split():
            user = self._resolve_user(identifier)
            if user is None:
                errors.append(f"`{identifier}` — не найден")
                continue
            if reward_id in user.reward_ids:
                errors.append(f"`{identifier}` — уже имеет это достижение")
            else:
                user.reward_ids.append(reward_id)
                resolved.append(f"`{identifier}` — ✅")
        await self.rewards.save()
        body = "\n".join(resolved + errors)
        await ctx.reply(
            f"Вручение {format_reward_html(reward)}:\n{body}",
            html=True, markdown=False,
        )

    @subcommand("<reward_id:int> take <users:rest>", description="Забрать", admin=True)
    async def take(self, ctx: FeatureContext, reward_id: int, users: str):
        reward = self.rewards.find_by(id=reward_id)
        if reward is None:
            await ctx.reply("Достижение не найдено")
            return
        if reward.dynamic_key:
            await ctx.reply("Динамическое достижение нельзя изъять вручную")
            return
        resolved, errors = [], []
        for identifier in users.split():
            user = self._resolve_user(identifier)
            if user is None:
                errors.append(f"`{identifier}` — не найден")
                continue
            if reward_id not in user.reward_ids:
                errors.append(f"`{identifier}` — не имеет это достижение")
            else:
                user.reward_ids.remove(reward_id)
                resolved.append(f"`{identifier}` — ✅")
        await self.rewards.save()
        body = "\n".join(resolved + errors)
        await ctx.reply(
            f"Изъятие {format_reward_html(reward)}:\n{body}",
            html=True, markdown=False,
        )

    @paginated("rewards", per_page=10, header="Достижения", parse_mode="HTML")
    def rewards_page(self, ctx: FeatureContext, metadata: str):
        items = list(self.rewards)

        def render(batch):
            entries: list[tuple[int, str]] = []
            for r in batch:
                text = format_reward_html(r)
                if r.dynamic_key:
                    holder_id = get_dynamic_reward_holder(self.repository, r)
                    if holder_id is not None:
                        name = get_holder_display_name(self.repository, holder_id)
                        text += f" → <code>{html_module.escape(name)}</code>"
                    else:
                        text += " → <i>нет владельца</i>"
                entries.append((r.id, text))
            return format_lined_list_html(items=entries, delimiter=". ")

        return items, render

    @wizard(
        "rewards:add",
        ask("name", "Название и описание достижения", validator=validate_message_text([])),
        ask("emoji", "Эмоджи достижения", validator=extract_emoji),
    )
    async def on_add_done(self, ctx: FeatureContext, name: str, emoji: dict):
        reward = self.rewards.add(Reward(
            id=0,
            name=name,
            emoji=emoji["text"],
            custom_emoji_id=emoji["custom_emoji_id"],
        ))
        await self.rewards.save()
        message = get_message(ctx.update)
        await message.chat.send_message(
            f"Достижение добавлено: {format_reward_html(reward)} (id: {reward.id})",
            parse_mode="HTML",
        )

    def _resolve_user(self, identifier: str):
        identifier = identifier.lstrip("@")
        try:
            return self.users.find_by(id=int(identifier))
        except ValueError:
            pass
        target = identifier.lower()
        return self.users.find_one(
            lambda u: u.username and u.username.lower() == target
        )

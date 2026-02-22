import html as html_module
import re

from telegram import MessageEntity

from steward.bot.context import ChatBotContext
from steward.data.models.reward import Reward, UserReward
from steward.dynamic_rewards import get_dynamic_reward_holder, get_holder_display_name
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.emoji import (
    extract_emoji,
    format_lined_list_html,
    format_reward_html,
)
from steward.helpers.keyboard import parse_and_validate_keyboard
from steward.helpers.pagination import (
    PageFormatContext,
    Paginator,
    parse_pagination,
)
from steward.helpers.tg_update_helpers import get_message
from steward.helpers.validation import validate_message_text
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.session_registry import get_session_key
from steward.session.steps.question_step import QuestionStep


class RewardListHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "rewards"):
            return False

        parts = context.message.text.split()
        if len(parts) > 1 and parts[1] not in ("list",):
            return False

        return await self._get_paginator().show_list(context.update)

    async def callback(self, context):
        pagination_parsed = parse_and_validate_keyboard(
            "rewards_list",
            context.callback_query.data,
            parse_func=parse_pagination,
        )
        if pagination_parsed is not None:
            return await self._get_paginator().process_parsed_callback(
                context.update, pagination_parsed
            )
        return False

    def _format_page(self, ctx: PageFormatContext[Reward]) -> str:
        items: list[tuple[int, str]] = []
        for r in ctx.data:
            text = format_reward_html(r)
            if r.dynamic_key:
                holder_id = get_dynamic_reward_holder(self.repository, r)
                if holder_id is not None:
                    name = get_holder_display_name(self.repository, holder_id)
                    text += f" → <code>{html_module.escape(name)}</code>"
                else:
                    text += " → <i>нет владельца</i>"
            items.append((r.id, text))
        return format_lined_list_html(items=items, delimiter=". ")

    def _get_paginator(self) -> Paginator:
        paginator = Paginator(
            unique_keyboard_name="rewards_list",
            list_header="Достижения",
            page_size=10,
            page_format_func=self._format_page,
            always_show_pagination=True,
            parse_mode="HTML",
        )
        paginator.data_func = lambda: list(self.repository.db.rewards)
        return paginator

    def help(self):
        return "/rewards [add|remove <id>|<id> present/take <users>] — управлять достижениями"

    def prompt(self):
        return (
            "▶ /rewards — управление достижениями\n"
            "  Список: /rewards\n"
            "  Добавить: /rewards add <название> <эмоджи> или /rewards add (начинает сессию)\n"
            "  Удалить: /rewards remove <id>\n"
            "  Вручить: /rewards <id> present <пользователи>\n"
            "  Забрать: /rewards <id> take <пользователи>\n"
            "  present и take — это ДВЕ ОТДЕЛЬНЫЕ команды, а НЕ одна.\n"
            "  Примеры:\n"
            "  - «покажи достижения» → /rewards\n"
            "  - «удали достижение 5» → /rewards remove 5\n"
            "  - «вручи достижение 3 пользователю @user» → /rewards 3 present @user"
        )


class RewardAddHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                QuestionStep(
                    "name",
                    "Название и описание достижения",
                    filter_answer=validate_message_text([]),
                ),
                QuestionStep(
                    "emoji",
                    "Эмоджи достижения",
                    filter_answer=extract_emoji,
                ),
            ]
        )

    async def chat(self, context):
        key = get_session_key(context.update)
        if key not in self.sessions and validate_command_msg(context.update, "rewards"):
            parts = context.message.text.split(maxsplit=2)
            if len(parts) >= 3 and parts[1] == "add":
                emoji_data = self._parse_inline_emoji(context.message, parts[2])
                if emoji_data:
                    max_id = max(
                        (r.id for r in self.repository.db.rewards), default=0
                    )
                    reward = Reward(
                        id=max_id + 1,
                        name=emoji_data["name"],
                        emoji=emoji_data["emoji_text"],
                        custom_emoji_id=emoji_data["custom_emoji_id"],
                    )
                    self.repository.db.rewards.append(reward)
                    await self.repository.save()
                    await context.message.reply_html(
                        f"Достижение добавлено: {format_reward_html(reward)} (id: {reward.id})"
                    )
                    return True
        return await super().chat(context)

    @staticmethod
    def _parse_inline_emoji(msg, text):
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

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "rewards"):
            return False
        parts = update.message.text.split()
        if len(parts) < 2 or parts[1] != "add":
            return False
        return True

    async def on_session_finished(self, update, session_context):
        emoji_data = session_context["emoji"]
        max_id = max((r.id for r in self.repository.db.rewards), default=0)
        reward = Reward(
            id=max_id + 1,
            name=session_context["name"],
            emoji=emoji_data["text"],
            custom_emoji_id=emoji_data["custom_emoji_id"],
        )
        self.repository.db.rewards.append(reward)
        await self.repository.save()

        message = get_message(update)
        await message.chat.send_message(
            f"Достижение добавлено: {format_reward_html(reward)} (id: {reward.id})",
            parse_mode="HTML",
        )

    def help(self):
        return None


class RewardRemoveHandler(Handler):
    only_for_admin = True

    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "rewards"):
            return False

        parts = context.message.text.split()
        if len(parts) < 3 or parts[1] != "remove":
            return False

        try:
            reward_id = int(parts[2])
        except ValueError:
            await context.message.reply_text("ID достижения должен быть числом")
            return True

        reward = next(
            (r for r in self.repository.db.rewards if r.id == reward_id), None
        )
        if reward is None:
            await context.message.reply_text("Достижение не найдено")
            return True

        if reward.dynamic_key:
            await context.message.reply_text("Динамическое достижение нельзя удалить")
            return True

        self.repository.db.rewards.remove(reward)
        self.repository.db.user_rewards = [
            ur for ur in self.repository.db.user_rewards if ur.reward_id != reward_id
        ]
        await self.repository.save()
        await context.message.reply_html(
            f"Достижение {format_reward_html(reward)} удалено"
        )
        return True

    def help(self):
        return None


class RewardPresentHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "rewards"):
            return False

        parts = context.message.text.split()
        if len(parts) < 4:
            return False

        try:
            reward_id = int(parts[1])
        except ValueError:
            return False

        if parts[2] != "present":
            return False

        reward = next(
            (r for r in self.repository.db.rewards if r.id == reward_id), None
        )
        if reward is None:
            await context.message.reply_text("Достижение не найдено")
            return True

        if reward.dynamic_key:
            await context.message.reply_text("Динамическое достижение нельзя вручить вручную")
            return True

        user_identifiers = parts[3:]
        resolved = []
        errors = []

        for identifier in user_identifiers:
            user = self._resolve_user(identifier)
            if user is None:
                errors.append(f"`{identifier}` — не найден")
            else:
                already = any(
                    ur.user_id == user.id and ur.reward_id == reward_id
                    for ur in self.repository.db.user_rewards
                )
                if already:
                    errors.append(f"`{identifier}` — уже имеет это достижение")
                else:
                    self.repository.db.user_rewards.append(
                        UserReward(user_id=user.id, reward_id=reward_id)
                    )
                    resolved.append(f"`{identifier}` — ✅")

        await self.repository.save()

        lines = resolved + errors
        await context.message.reply_html(
            f"Вручение {format_reward_html(reward)}:\n" + "\n".join(lines)
        )
        return True

    def _resolve_user(self, identifier: str):
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
        return None


class RewardTakeHandler(Handler):
    only_for_admin = True

    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "rewards"):
            return False

        parts = context.message.text.split()
        if len(parts) < 4:
            return False

        try:
            reward_id = int(parts[1])
        except ValueError:
            return False

        if parts[2] != "take":
            return False

        reward = next(
            (r for r in self.repository.db.rewards if r.id == reward_id), None
        )
        if reward is None:
            await context.message.reply_text("Достижение не найдено")
            return True

        if reward.dynamic_key:
            await context.message.reply_text("Динамическое достижение нельзя изъять вручную")
            return True

        user_identifiers = parts[3:]
        resolved = []
        errors = []

        for identifier in user_identifiers:
            user = self._resolve_user(identifier)
            if user is None:
                errors.append(f"`{identifier}` — не найден")
                continue

            ur = next(
                (
                    ur
                    for ur in self.repository.db.user_rewards
                    if ur.user_id == user.id and ur.reward_id == reward_id
                ),
                None,
            )
            if ur is None:
                errors.append(f"`{identifier}` — не имеет это достижение")
            else:
                self.repository.db.user_rewards.remove(ur)
                resolved.append(f"`{identifier}` — ✅")

        await self.repository.save()

        lines = resolved + errors
        await context.message.reply_html(
            f"Изъятие {format_reward_html(reward)}:\n" + "\n".join(lines)
        )
        return True

    def _resolve_user(self, identifier: str):
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
        return None

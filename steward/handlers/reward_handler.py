from steward.bot.context import ChatBotContext
from steward.data.models.reward import Reward, UserReward
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
from steward.session.steps.question_step import QuestionStep


def format_rewards_page(ctx: PageFormatContext[Reward]) -> str:
    return format_lined_list_html(
        items=[(r.id, format_reward_html(r)) for r in ctx.data],
        delimiter=". ",
    )


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

    def _get_paginator(self) -> Paginator:
        paginator = Paginator(
            unique_keyboard_name="rewards_list",
            list_header="Достижения",
            page_size=10,
            page_format_func=format_rewards_page,
            always_show_pagination=True,
            parse_mode="HTML",
        )
        paginator.data_func = lambda: list(self.repository.db.rewards)
        return paginator

    def help(self):
        return "/rewards [add|remove <id>|<id> present/take <users>] — управлять достижениями"


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

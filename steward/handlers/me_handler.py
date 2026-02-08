from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import CallbackBotContext, ChatBotContext
from steward.data.models.reward import Reward
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.emoji import (
    format_lined_list_html,
    format_reward_emoji,
    format_reward_html,
)
from steward.helpers.keyboard import parse_and_validate_keyboard
from steward.helpers.pagination import (
    PageFormatContext,
    PaginationParseResult,
    Paginator,
    parse_pagination,
)


def format_rewards_page(ctx: PageFormatContext[Reward]) -> str:
    return format_lined_list_html(
        items=[(r.id, format_reward_html(r)) for r in ctx.data],
        delimiter=". ",
    )


class MeHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "me"):
            return False

        user_id = context.message.from_user.id
        rewards_map = {r.id: r for r in self.repository.db.rewards}
        user_reward_ids = [
            ur.reward_id
            for ur in self.repository.db.user_rewards
            if ur.user_id == user_id
        ]
        user_rewards = [rewards_map[rid] for rid in user_reward_ids if rid in rewards_map]

        emojis = (
            " ".join(format_reward_emoji(r) for r in user_rewards)
            if user_rewards
            else "нет"
        )

        text = f"Профиль\n\nДостижения: {emojis}"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Достижения",
                    callback_data=f"me_rewards|{user_id}",
                )
            ]
        ])

        await context.message.reply_html(text, reply_markup=keyboard)
        return True

    async def callback(self, context: CallbackBotContext):
        parsed = parse_and_validate_keyboard(
            "me_rewards",
            context.callback_query.data,
        )
        if parsed is not None:
            user_id = int(parsed.metadata)
            paginator = self._get_paginator(user_id)
            text, keyboard = paginator._get_data_page()
            await context.callback_query.message.chat.send_message(
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([keyboard]) if keyboard else None,
            )
            return True

        pagination_parsed = parse_and_validate_keyboard(
            "me_rewards_list",
            context.callback_query.data,
            parse_func=parse_pagination,
        )
        if pagination_parsed is not None:
            user_id = int(pagination_parsed.metadata)
            return await self._get_paginator(user_id).process_parsed_callback(
                context.update, pagination_parsed
            )

        return False

    def _get_paginator(self, user_id: int) -> Paginator:
        rewards_map = {r.id: r for r in self.repository.db.rewards}

        paginator = Paginator(
            unique_keyboard_name="me_rewards_list",
            list_header="Ваши достижения",
            page_size=10,
            page_format_func=format_rewards_page,
            parse_mode="HTML",
        )
        paginator.data_func = lambda: [
            rewards_map[ur.reward_id]
            for ur in self.repository.db.user_rewards
            if ur.user_id == user_id and ur.reward_id in rewards_map
        ]
        paginator.metadata = str(user_id)
        return paginator

    def help(self):
        return "/me - профиль"

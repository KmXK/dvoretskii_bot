import html as html_module

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import CallbackBotContext, ChatBotContext
from steward.data.models.reward import Reward
from steward.dynamic_rewards import get_dynamic_reward_holder, get_holder_display_name
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
    get_data_page,
    parse_pagination,
)


class MeHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "me"):
            return False

        user_id = context.message.from_user.id
        text, keyboard = self._build_profile(user_id)
        await context.message.reply_html(text, reply_markup=keyboard)
        return True

    async def callback(self, context: CallbackBotContext):
        parsed = parse_and_validate_keyboard(
            "me_rewards",
            context.callback_query.data,
        )
        if parsed is not None:
            user_id = int(parsed.metadata)
            text, keyboard = self._build_rewards(user_id, 0)
            await context.callback_query.message.edit_text(
                text=text, parse_mode="HTML", reply_markup=keyboard,
            )
            return True

        back_parsed = parse_and_validate_keyboard(
            "me_back",
            context.callback_query.data,
        )
        if back_parsed is not None:
            user_id = int(back_parsed.metadata)
            text, keyboard = self._build_profile(user_id)
            await context.callback_query.message.edit_text(
                text=text, parse_mode="HTML", reply_markup=keyboard,
            )
            return True

        pagination_parsed = parse_and_validate_keyboard(
            "me_rewards_list",
            context.callback_query.data,
            parse_func=parse_pagination,
        )
        if pagination_parsed is not None:
            if pagination_parsed.is_current_page:
                return True
            user_id = int(pagination_parsed.metadata)
            text, keyboard = self._build_rewards(user_id, pagination_parsed.page_number)
            await context.callback_query.message.edit_text(
                text=text, parse_mode="HTML", reply_markup=keyboard,
            )
            return True

        return False

    def _build_profile(self, user_id: int):
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

        user = next((u for u in self.repository.db.users if u.id == user_id), None)
        monkeys = user.monkeys if user else 0

        text = f"Профиль\n\n🐵 Обезьянки: {monkeys}\nДостижения: {emojis}"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Достижения",
                    callback_data=f"me_rewards|{user_id}",
                )
            ]
        ])

        return text, keyboard

    def _format_rewards_page(self, ctx: PageFormatContext[Reward]) -> str:
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

    def _build_rewards(self, user_id: int, page: int):
        rewards_map = {r.id: r for r in self.repository.db.rewards}
        user_rewards = [
            rewards_map[ur.reward_id]
            for ur in self.repository.db.user_rewards
            if ur.user_id == user_id and ur.reward_id in rewards_map
        ]

        text, pagination_buttons = get_data_page(
            data=user_rewards,
            page=page,
            page_size=10,
            list_header="Ваши достижения",
            unique_keyboard_name="me_rewards_list",
            page_format_func=self._format_rewards_page,
            always_show_pagination=True,
            metadata=str(user_id),
        )

        rows = []
        if pagination_buttons:
            rows.append(pagination_buttons)
        rows.append([
            InlineKeyboardButton(
                "← Назад", callback_data=f"me_back|{user_id}",
            )
        ])

        return text, InlineKeyboardMarkup(rows)

    def help(self):
        return "/me - профиль"

    def prompt(self):
        return (
            "▶ /me — профиль пользователя\n"
            "  Без аргументов: /me\n"
            "  Примеры:\n"
            "  - «покажи мой профиль» → /me\n"
            "  - «мой профиль» → /me"
        )
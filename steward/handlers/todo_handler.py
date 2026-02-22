from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import ChatBotContext
from steward.data.models.reward import Reward, UserReward
from steward.data.models.todo_item import TodoItem
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.emoji import extract_emoji, format_reward_html
from steward.helpers.formats import format_lined_list
from steward.helpers.keyboard import parse_and_validate_keyboard
from steward.helpers.pagination import (
    PageFormatContext,
    Paginator,
    parse_pagination,
)
from steward.helpers.tg_update_helpers import get_message
from steward.helpers.validation import check, try_get, validate_message_text
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.session_registry import get_session_key
from steward.session.step import Step
from steward.session.steps.jump_step import JumpStep
from steward.session.steps.question_step import QuestionStep


def format_todo_page(ctx: PageFormatContext[TodoItem]) -> str:
    return format_lined_list(
        items=[(item.id, item.text) for item in ctx.data],
        delimiter=". ",
    )


class TodoListHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "todo"):
            return False

        parts = context.message.text.split()
        if len(parts) > 1 and parts[1] not in ("list",):
            return False

        chat_id = context.message.chat.id
        return await self._get_paginator(chat_id).show_list(context.update)

    async def callback(self, context):
        pagination_parsed = parse_and_validate_keyboard(
            "todo_list",
            context.callback_query.data,
            parse_func=parse_pagination,
        )
        if pagination_parsed is not None:
            chat_id = int(pagination_parsed.metadata)
            return await self._get_paginator(chat_id).process_parsed_callback(
                context.update, pagination_parsed
            )
        return False

    def _get_paginator(self, chat_id: int) -> Paginator:
        paginator = Paginator(
            unique_keyboard_name="todo_list",
            list_header="Список событий",
            page_size=10,
            page_format_func=format_todo_page,
            always_show_pagination=True,
        )
        paginator.data_func = lambda: [
            t
            for t in self.repository.db.todo_items
            if t.chat_id == chat_id and not t.is_done
        ]
        paginator.metadata = str(chat_id)
        return paginator

    def help(self):
        return "/todo [remove <id>|done <id>] | [text] — управлять событиями"

    def prompt(self):
        return (
            "▶ /todo — управление событиями\n"
            "  Добавить: /todo <текст>\n"
            "  Отметить выполненным: /todo done <id>\n"
            "  Удалить: /todo remove <id>\n"
            "  Список: /todo\n"
            "  Примеры:\n"
            "  - «добавь в туду купить молоко» → /todo купить молоко\n"
            "  - «отметь задачу 3 выполненной» → /todo done 3\n"
            "  - «удали задачу 5» → /todo remove 5\n"
            "  - «покажи список дел» → /todo"
        )


_TODO_SUBCOMMANDS = ("list", "done", "remove")


class TodoAddHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "todo"):
            return False
        parts = context.message.text.split(maxsplit=1)
        if len(parts) < 2:
            return False
        text = parts[1].strip()
        if not text or text.split()[0] in _TODO_SUBCOMMANDS:
            return False

        max_id = max(
            (t.id for t in self.repository.db.todo_items), default=0
        )
        todo = TodoItem(
            id=max_id + 1,
            chat_id=context.message.chat.id,
            text=text,
        )
        self.repository.db.todo_items.append(todo)
        await self.repository.save()
        await context.message.reply_text(f"Событие добавлено (id: {todo.id})")
        return True

    def help(self):
        return None


class TodoRemoveHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "todo"):
            return False

        parts = context.message.text.split()
        if len(parts) < 3 or parts[1] != "remove":
            return False

        try:
            todo_id = int(parts[2])
        except ValueError:
            await context.message.reply_text("ID события должен быть числом")
            return True

        chat_id = context.message.chat.id
        todo = next(
            (
                t
                for t in self.repository.db.todo_items
                if t.id == todo_id and t.chat_id == chat_id
            ),
            None,
        )
        if todo is None:
            await context.message.reply_text("Событие не найдено")
            return True

        self.repository.db.todo_items.remove(todo)
        await self.repository.save()
        await context.message.reply_text(f"Событие \"{todo.text}\" удалено")
        return True

    def help(self):
        return None


class MarkDoneStep(Step):
    def __init__(self):
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            todo_id = context.session_context["todo_id"]
            chat_id = context.session_context["chat_id"]
            todo = next(
                t
                for t in context.repository.db.todo_items
                if t.id == todo_id and t.chat_id == chat_id and not t.is_done
            )
            todo.is_done = True
            await context.repository.save()

            await context.message.reply_text(
                f"Событие \"{todo.text}\" завершено!\n\nХотите добавить достижение?",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "Да", callback_data="todo_done_reward|yes"
                        ),
                        InlineKeyboardButton(
                            "Нет", callback_data="todo_done_reward|no"
                        ),
                    ]
                ]),
            )
            self.is_waiting = True
            return False
        return False

    async def callback(self, context):
        if not self.is_waiting:
            return False
        data = context.callback_query.data
        if data == "todo_done_reward|yes":
            context.session_context["add_reward"] = True
            await context.callback_query.message.edit_reply_markup(reply_markup=None)
            self.is_waiting = False
            return True
        elif data == "todo_done_reward|no":
            context.session_context["add_reward"] = False
            await context.callback_query.message.edit_reply_markup(reply_markup=None)
            self.is_waiting = False
            return True
        return False

    def stop(self):
        self.is_waiting = False


class TodoDoneHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__([
            MarkDoneStep(),
            JumpStep(
                "skip_reward",
                4,
                lambda c: not c.get("add_reward", True),
            ),
            QuestionStep(
                "reward_name",
                "Название достижения",
                filter_answer=validate_message_text([]),
            ),
            QuestionStep(
                "reward_emoji",
                "Эмоджи достижения",
                filter_answer=extract_emoji,
            ),
            QuestionStep(
                "reward_users",
                "Кому присвоить? (username или id через пробел)",
                filter_answer=validate_message_text([
                    try_get(lambda t: t.split()),
                    check(
                        lambda ids: len(ids) > 0,
                        "Укажите хотя бы одного пользователя",
                    ),
                ]),
            ),
        ])

    async def chat(self, context):
        key = get_session_key(context.update)
        if key not in self.sessions:
            if validate_command_msg(context.update, "todo"):
                parts = context.message.text.split()
                if len(parts) >= 3 and parts[1] == "done":
                    try:
                        todo_id = int(parts[2])
                    except ValueError:
                        await context.message.reply_text(
                            "ID события должен быть числом"
                        )
                        return True

                    chat_id = context.message.chat.id
                    todo = next(
                        (
                            t
                            for t in self.repository.db.todo_items
                            if t.id == todo_id and t.chat_id == chat_id
                        ),
                        None,
                    )
                    if todo is None:
                        await context.message.reply_text("Событие не найдено")
                        return True
                    if todo.is_done:
                        await context.message.reply_text("Событие уже завершено")
                        return True

        return await super().chat(context)

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "todo"):
            return False
        parts = update.message.text.split()
        if len(parts) != 3 or parts[1] != "done":
            return False
        try:
            todo_id = int(parts[2])
        except ValueError:
            return False

        chat_id = update.message.chat.id
        todo = next(
            (
                t
                for t in self.repository.db.todo_items
                if t.id == todo_id and t.chat_id == chat_id and not t.is_done
            ),
            None,
        )
        if todo is None:
            return False

        session_context["todo_id"] = todo_id
        session_context["chat_id"] = chat_id
        return True

    async def on_session_finished(self, update, session_context):
        if not session_context.get("add_reward"):
            return

        emoji_data = session_context["reward_emoji"]
        max_id = max(
            (r.id for r in self.repository.db.rewards), default=0
        )
        reward = Reward(
            id=max_id + 1,
            name=session_context["reward_name"],
            emoji=emoji_data["text"],
            custom_emoji_id=emoji_data["custom_emoji_id"],
        )
        self.repository.db.rewards.append(reward)

        assigned = 0
        for identifier in session_context["reward_users"]:
            user = self._resolve_user(identifier)
            if user is not None:
                self.repository.db.user_rewards.append(
                    UserReward(user_id=user.id, reward_id=reward.id)
                )
                assigned += 1

        await self.repository.save()

        message = get_message(update)
        await message.chat.send_message(
            f"Достижение {format_reward_html(reward)} создано и вручено ({assigned})",
            parse_mode="HTML",
        )

    def _resolve_user(self, identifier: str):
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
        return None

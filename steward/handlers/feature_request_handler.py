import datetime
import re
from enum import Enum

from telegram import InlineKeyboardButton, Message

from steward.bot.context import ChatBotContext
from steward.data.models.feature_request import (
    FeatureRequest,
    FeatureRequestChange,
    FeatureRequestStatus,
)
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.formats import escape_markdown, format_lined_list
from steward.helpers.keyboard import parse_and_validate_keyboard
from steward.helpers.pagination import (
    PageFormatContext,
    PaginationParseResult,
    Paginator,
    parse_pagination,
)

STATUS_LABELS = {
    FeatureRequestStatus.OPEN: "Открыт",
    FeatureRequestStatus.DONE: "Завершён",
    FeatureRequestStatus.DENIED: "Отклонён",
    FeatureRequestStatus.IN_PROGRESS: "В работе",
    FeatureRequestStatus.TESTING: "На тестировании",
}

PRIORITY_EMOJI = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🔵", 5: "⚪"}


def format_page(ctx: PageFormatContext[FeatureRequest]) -> str:
    def format_fr(fr: FeatureRequest):
        author = escape_markdown(fr.author_name)
        text = escape_markdown(fr.text)
        text = re.sub(r"@[a-zA-Z0-9]+", lambda m: f"`{m.group(0)}`", text)
        p_emoji = PRIORITY_EMOJI.get(fr.priority, "⚪")
        return f"{p_emoji} `{author}`: {text}"

    return format_lined_list(
        items=[(fr.id, format_fr(fr)) for fr in ctx.data], delimiter=". "
    )


class FilterType(Enum):
    ALL = 0
    DONE = 1
    DENIED = 2
    OPENED = 3
    IN_PROGRESS = 4
    TESTING = 5


class FeatureRequestViewHandler(Handler):
    async def chat(self, context):
        if not validate_command_msg(context.update, ["fr", "featurerequest"]):
            return False

        assert context.message.text

        data = context.message.text.split(" ")
        if len(data) == 1 or data[1] == "list":
            return await self._get_paginator(FilterType.OPENED).show_list(
                context.update
            )

        if len(data) >= 3 and data[1].isdigit():
            fr_id = int(data[1])
            subcommand = data[2].lower()

            if subcommand == "priority":
                return await self._set_priority(context, fr_id, data[3:])

            if subcommand == "note":
                note_text = " ".join(data[3:])
                return await self._add_note(context, fr_id, note_text)

        if len(data) == 2 and data[1].isdigit():
            return await self._show_feature_request(context, int(data[1]))

        return await self._add_feature(
            context.message, context.message.text[len(data[0]) :].strip()
        )

    async def callback(self, context):
        assert context.callback_query.data

        filter_parsed = parse_and_validate_keyboard(
            "feature_request_filter",
            context.callback_query.data,
        )

        if filter_parsed is not None:
            return await self._get_paginator(
                FilterType(int(filter_parsed.metadata))
            ).process_parsed_callback(
                context.update,
                PaginationParseResult(
                    unique_keyboard_name="feature_request_list",
                    metadata=filter_parsed.metadata,
                    is_current_page=False,
                    page_number=0,
                ),
            )

        pagination_parsed = parse_and_validate_keyboard(
            "feature_request_list",
            context.callback_query.data,
            parse_func=parse_pagination,
        )

        if pagination_parsed is not None:
            return await self._get_paginator(
                FilterType(int(pagination_parsed.metadata))
            ).process_parsed_callback(
                context.update,
                pagination_parsed,
            )

        return False

    def _create_filter_keyboard(self, type: FilterType):
        callbacks = [
            x
            for x in [
                ("Все", FilterType.ALL),
                ("Завершённые", FilterType.DONE),
                ("Отклонённые", FilterType.DENIED),
                ("Открытые", FilterType.OPENED),
                ("В работе", FilterType.IN_PROGRESS),
                ("Тестирование", FilterType.TESTING),
            ]
            if x[1] != type
        ]

        return [
            InlineKeyboardButton(
                text,
                callback_data=f"feature_request_filter|{type.value}",
            )
            for (text, type) in callbacks
        ]

    async def _show_feature_request(self, context: ChatBotContext, id: int):
        if id <= 0 or id > len(self.repository.db.feature_requests):
            await context.message.reply_text(
                "Фича-реквеста с таким номером не существует"
            )
            return True

        fr = self.repository.db.feature_requests[id - 1]

        status_text = STATUS_LABELS.get(fr.status, "Неизвестен")
        p_emoji = PRIORITY_EMOJI.get(fr.priority, "⚪")

        escaped_text = escape_markdown(fr.text)
        formatted_text = re.sub(
            r"@[a-zA-Z0-9]+", lambda m: f"`{m.group(0)}`", escaped_text
        )
        escaped_author = escape_markdown(fr.author_name)

        date_str = ""
        if fr.creation_timestamp:
            dt = datetime.datetime.fromtimestamp(fr.creation_timestamp)
            date_str = f"\nДата: {dt.strftime('%d.%m.%Y %H:%M')}"

        history_text = ""
        if fr.history:
            history_text = "\n\nИстория изменений:"
            for change in fr.history:
                change_dt = datetime.datetime.fromtimestamp(change.timestamp)
                change_status = STATUS_LABELS.get(change.status, "Неизвестен")
                history_text += (
                    f"\n• {change_status} ({change_dt.strftime('%d.%m.%Y %H:%M')})"
                )

        notes_text = ""
        if fr.notes:
            notes_text = "\n\nПримечания:"
            for i, note in enumerate(fr.notes, 1):
                escaped_note = escape_markdown(note)
                notes_text += f"\n{i}\\. {escaped_note}"

        message_text = (
            f"Фича-реквест #{fr.id}\n"
            f"Статус: {status_text}\n"
            f"Приоритет: {p_emoji} {fr.priority}\n"
            f"Автор: `{escaped_author}`\n"
            f"Текст: {formatted_text}"
            f"{date_str}"
            f"{history_text}"
            f"{notes_text}"
        )

        await context.message.reply_markdown(message_text)
        return True

    async def _set_priority(self, context: ChatBotContext, fr_id: int, args: list[str]):
        if not args or not args[0].isdigit():
            await context.message.reply_text("Укажите приоритет от 1 до 5")
            return True

        priority = int(args[0])
        if priority < 1 or priority > 5:
            await context.message.reply_text("Приоритет должен быть от 1 до 5")
            return True

        if fr_id <= 0 or fr_id > len(self.repository.db.feature_requests):
            await context.message.reply_text(
                "Фича-реквеста с таким номером не существует"
            )
            return True

        fr = self.repository.db.feature_requests[fr_id - 1]

        user_id = context.message.from_user.id
        if fr.author_id != user_id and not self.repository.is_admin(user_id):
            await context.message.reply_text(
                "Вы не можете изменять приоритет этого фича-реквеста"
            )
            return True

        fr.priority = priority
        await self.repository.save()

        p_emoji = PRIORITY_EMOJI.get(priority, "⚪")
        await context.message.reply_text(
            f"Приоритет фича-реквеста #{fr_id} изменён на {p_emoji} {priority}"
        )
        return True

    async def _add_note(self, context: ChatBotContext, fr_id: int, note_text: str):
        if not note_text.strip():
            await context.message.reply_text("Укажите текст примечания")
            return True

        if fr_id <= 0 or fr_id > len(self.repository.db.feature_requests):
            await context.message.reply_text(
                "Фича-реквеста с таким номером не существует"
            )
            return True

        fr = self.repository.db.feature_requests[fr_id - 1]

        user_id = context.message.from_user.id
        if fr.author_id != user_id and not self.repository.is_admin(user_id):
            await context.message.reply_text(
                "Вы не можете добавлять примечания к этому фича-реквесту"
            )
            return True

        fr.notes.append(note_text.strip())
        await self.repository.save()

        await context.message.reply_text(
            f"Примечание добавлено к фича-реквесту #{fr_id}"
        )
        return True

    async def _add_feature(self, message: Message, text):
        self.repository.db.feature_requests.append(
            FeatureRequest(
                id=len(self.repository.db.feature_requests) + 1,
                author_name=message.from_user.name,
                text=text,
                author_id=message.from_user.id,
                message_id=message.message_id,
                chat_id=message.chat_id,
                creation_timestamp=datetime.datetime.now().timestamp(),
            )
        )
        await self.repository.save()
        await message.reply_text("Фича-реквест добавлен")
        return True

    def _get_paginator(self, type: FilterType) -> Paginator:
        paginator = Paginator(
            unique_keyboard_name="feature_request_list",
            list_header="Фича реквесты",
            page_size=15,
            page_format_func=format_page,
            always_show_pagination=True,
        )

        status_filters = {
            FilterType.ALL: lambda x: True,
            FilterType.DONE: lambda x: x.status == FeatureRequestStatus.DONE,
            FilterType.DENIED: lambda x: x.status == FeatureRequestStatus.DENIED,
            FilterType.OPENED: lambda x: x.status == FeatureRequestStatus.OPEN,
            FilterType.IN_PROGRESS: lambda x: x.status == FeatureRequestStatus.IN_PROGRESS,
            FilterType.TESTING: lambda x: x.status == FeatureRequestStatus.TESTING,
        }

        filter_func = status_filters.get(type, lambda x: True)

        paginator.data_func = lambda: sorted(
            filter(filter_func, self.repository.db.feature_requests),
            key=lambda fr: fr.priority,
        )
        paginator.metadata = str(type.value)
        paginator.keyboard_decorator = lambda x: [
            x,
            self._create_filter_keyboard(type),
        ]

        return paginator

    def help(self):
        return "/fr [id|list|done|deny|reopen|inprogress|testing <ids>] | [<id> priority <1-5>] | [<id> note <text>] | [text] - управлять фича-реквестами"

    def prompt(self):
        return (
            "▶ /fr — управление фича-реквестами\n"
            "  Добавить: /fr <текст>\n"
            "  Список: /fr list\n"
            "  Просмотр: /fr <id>\n"
            "  Сменить статус: /fr done <id>, /fr deny <id>, /fr reopen <id>, /fr inprogress <id>, /fr testing <id>\n"
            "  Приоритет: /fr <id> priority <1-5>\n"
            "  Примечание: /fr <id> note <текст>\n"
            "  Примеры:\n"
            "  - «добавь фичу тёмная тема» → /fr тёмная тема\n"
            "  - «покажи фича-реквесты» → /fr list\n"
            "  - «отметь фичу 7 выполненной» → /fr done 7\n"
            "  - «установи приоритет 1 для фичи 3» → /fr 3 priority 1"
        )


class FeatureRequestEditHandler(Handler):
    async def chat(self, context):
        if not validate_command_msg(context.update, ["featurerequest", "fr"]):
            return False

        data = context.message.text.split(" ")

        if len(data) < 2:
            return False

        status_commands = {
            "done": (
                [
                    "Фича-реквест уже выполнен",
                    "Фича-реквест уже отклонён",
                    None,
                    None,
                    None,
                ],
                FeatureRequestStatus.DONE,
            ),
            "deny": (
                [
                    "Фича-реквест уже выполнен",
                    "Фича-реквест уже отклонён",
                    None,
                    None,
                    None,
                ],
                FeatureRequestStatus.DENIED,
            ),
            "reopen": (
                [
                    None,
                    None,
                    "Фича-реквест и так открыт",
                    None,
                    None,
                ],
                FeatureRequestStatus.OPEN,
            ),
            "inprogress": (
                [
                    None,
                    None,
                    None,
                    "Фича-реквест уже в работе",
                    None,
                ],
                FeatureRequestStatus.IN_PROGRESS,
            ),
            "testing": (
                [
                    None,
                    None,
                    None,
                    None,
                    "Фича-реквест уже на тестировании",
                ],
                FeatureRequestStatus.TESTING,
            ),
        }

        if data[1] in status_commands:
            if len(data) < 3:
                await context.message.reply_text("Укажите номера фичи-реквеста(ов)")
                return True

            error_list, new_status = status_commands[data[1]]
            return await self._command(error_list, new_status)(context, data[2:])

        return False

    def _command(
        self,
        error_list: list[str | None],
        new_status: FeatureRequestStatus,
    ):
        async def wrapper(context: ChatBotContext, ids):
            results = []
            for id in ids:
                if not id.isdigit():
                    results.append((id, "Неверный номер фичи-реквеста", None))
                    continue

                id = int(id)
                if id <= 0 or id > len(self.repository.db.feature_requests):
                    results.append(
                        (id, "Фича-реквеста с таким номером не существует", None)
                    )
                    continue

                fr = self.repository.db.feature_requests[id - 1]

                error = self._validate_fr(
                    context,
                    fr,
                    error_list,
                )

                if error is not None:
                    results.append((fr.id, error, None))
                    continue

                fr.history.append(
                    FeatureRequestChange(
                        author_id=context.message.from_user.id,
                        timestamp=datetime.datetime.now().timestamp(),
                        message_id=context.message.message_id,
                        status=new_status,
                    )
                )
                results.append((fr.id, None, fr.text))

            await self.repository.save()

            results.sort(key=lambda x: x[1] is None)

            is_closing = new_status in [
                FeatureRequestStatus.DONE,
                FeatureRequestStatus.DENIED,
            ]
            formatted_results = []
            for id, error, text in results:
                if error is None and text is not None and is_closing:
                    formatted_text = re.sub(
                        "@[a-zA-Z0-9]+", lambda m: f"`{m.group(0)}`", text
                    )
                    formatted_results.append((id, f"✅ {formatted_text}"))
                elif error is None:
                    formatted_results.append((id, "✅"))
                else:
                    formatted_results.append((id, error))

            await context.message.reply_markdown(format_lined_list(formatted_results))

            return True

        return wrapper

    def _validate_fr(
        self,
        context: ChatBotContext,
        fr: FeatureRequest,
        messages: list[str | None],
    ):
        validation_statuses = [
            FeatureRequestStatus.DONE,
            FeatureRequestStatus.DENIED,
            FeatureRequestStatus.OPEN,
            FeatureRequestStatus.IN_PROGRESS,
            FeatureRequestStatus.TESTING,
        ]

        for i, validation_status in enumerate(validation_statuses):
            if fr.status == validation_status and messages[i] is not None:
                return messages[i]

        user_id = context.message.from_user.id

        if fr.author_id != user_id and not self.repository.is_admin(user_id):
            return "Вы не можете редактировать статус этого фича-реквеста"

        return None

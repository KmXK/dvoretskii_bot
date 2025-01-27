import datetime
import re
from enum import Enum
from typing import Callable, Optional

from telegram import InlineKeyboardButton, Update

from handlers.handler import Handler, validate_command_msg
from helpers.formats import format_lined_list
from helpers.keyboard import KeyboardParseResult, parse_and_validate_keyboard
from helpers.pagination import (
    PageFormatContext,
    PaginationParseResult,
    Paginator,
    parse_pagination,
)
from models.feature_request import FeatureRequest
from repository import Repository


def format_page(ctx: PageFormatContext[FeatureRequest]) -> str:
    def format_fq(fq: FeatureRequest):
        return f"`{fq.author_name}`: {re.sub('@[a-zA-Z0-9]+', lambda m: f'`{m.group(0)}`', fq.text)}"

    return format_lined_list(
        items=[(fq.id, format_fq(fq)) for fq in ctx.data], delimiter=". "
    )


class FilterType(Enum):
    ALL = 0
    DONE = 1
    DENIED = 2
    OPENED = 3


class FeatureRequestViewHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        if not validate_command_msg(update, ["featurerequest", "fq"]):
            return False

        data = update.message.text.split(" ")
        if len(data) == 1 or data[1] == "list":
            return await self._get_paginator(FilterType.ALL).show_list(update)

        return await self._add_feature(
            update, update.message.text[len(data[0]) :].strip()
        )

    async def callback(self, update, context):
        parsed: Optional[KeyboardParseResult] = parse_and_validate_keyboard(
            "feature_request_filter",
            update.callback_query.data,
        )

        if parsed is not None:
            return await self._get_paginator(
                FilterType(int(parsed.metadata))
            ).process_parsed_callback(
                update,
                PaginationParseResult(
                    unique_keyboard_name="feature_request_list",
                    metadata=parsed.metadata,
                    is_current_page=False,
                    page_number=0,
                ),
            )

        parsed: Optional[PaginationParseResult] = parse_and_validate_keyboard(
            "feature_request_list",
            update.callback_query.data,
            parse_func=parse_pagination,
        )

        if parsed is not None:
            return await self._get_paginator(
                FilterType(int(parsed.metadata))
            ).process_parsed_callback(
                update,
                parsed,
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

    async def _add_feature(self, update: Update, text):
        self.repository.db.feature_requests.append(
            FeatureRequest(
                id=len(self.repository.db.feature_requests) + 1,
                author_name=update.message.from_user.name,
                text=text,
                author_id=update.message.from_user.id,
                message_id=update.message.message_id,
                chat_id=update.message.chat_id,
                creation_timestamp=datetime.datetime.now().timestamp(),
            )
        )
        self.repository.save()
        await update.message.reply_text("Фича-реквест добавлен")
        return True

    def _get_paginator(self, type: FilterType) -> Paginator:
        paginator = Paginator(
            unique_keyboard_name="feature_request_list",
            list_header="Фича реквесты",
            page_size=15,
            page_format_func=format_page,
            always_show_pagination=True,
        )

        filters = [
            lambda x: x,
            lambda x: x.done_timestamp is not None,
            lambda x: x.deny_timestamp is not None,
            lambda x: x.done_timestamp is None and x.deny_timestamp is None,
        ]

        paginator.data_func = lambda: [
            *filter(
                filters[type.value],
                self.repository.db.feature_requests,
            ),
        ]
        paginator.metadata = str(type.value)
        paginator.keyboard_decorator = lambda x: [
            x,
            self._create_filter_keyboard(type),
        ]

        return paginator

    def help(self):
        return "/featurerequest - посмотреть или добавить фича-реквест(ы)"


class FeatureRequestEditHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        if not validate_command_msg(update, ["featurerequest", "fq"]):
            return False

        data = update.message.text.split(" ")

        if len(data) < 2:
            return False

        if data[1] in ["done", "deny", "reopen"]:
            if len(data) < 3:
                await update.message.reply_text("Укажите номера фичи-реквеста(ов)")
                return True

            def reopen(fq):
                fq.done_timestamp = fq.deny_timestamp = None

            def done(fq):
                fq.done_timestamp = datetime.datetime.now().timestamp()

            def deny(fq):
                fq.deny_timestamp = datetime.datetime.now().timestamp()

            return await {
                "done": self._command(
                    [
                        "Фича-реквест уже выполнен",
                        "Фича-реквест уже отклонён",
                        None,
                    ],
                    done,
                ),
                "deny": self._command(
                    [
                        "Фича-реквест уже выполнен",
                        "Фича-реквест уже отклонён",
                        None,
                    ],
                    deny,
                ),
                "reopen": self._command(
                    [
                        None,
                        None,
                        "Фича-реквест и так открыт",
                    ],
                    reopen,
                ),
            }[data[1]](update, data[2:])

        return False

    def _command(
        self,
        error_list: list[str | None],
        func: Callable[[FeatureRequest], None],
    ):
        async def wrapper(update: Update, ids):
            results = []
            for id in ids:
                if not id.isdigit():
                    results.append((id, "Неверный номер фичи-реквеста"))
                    continue

                id = int(id)
                if id <= 0 or id > len(self.repository.db.feature_requests):
                    results.append((id, "Фича-реквеста с таким номером не существует"))
                    continue

                fq = self.repository.db.feature_requests[id - 1]

                error = self._validate_fq(
                    fq,
                    error_list,
                )

                if error is not None:
                    results.append((fq.id, error))
                    continue

                func(fq)
                results.append((fq.id, None))

            self.repository.save()

            results.sort(key=lambda x: x[1] is None)
            await update.message.reply_markdown(
                format_lined_list([
                    (id, "✅" if result is None else result) for id, result in results
                ])
            )

            return True

        return wrapper

    def _validate_fq(self, fq, messages: list[str | None]):
        validations = [
            lambda x: x.done_timestamp is not None,
            lambda x: x.deny_timestamp is not None,
            lambda x: x.done_timestamp is None and x.deny_timestamp is None,
        ]

        for i, validation in enumerate(validations):
            if validation(fq) and messages[i] is not None:
                return messages[i]

        return None

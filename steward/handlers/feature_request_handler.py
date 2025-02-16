import datetime
import re
from enum import Enum

from telegram import InlineKeyboardButton, Update

from steward.data.models.feature_request import (
    FeatureRequest,
    FeatureRequestChange,
    FeatureRequestStatus,
)
from steward.data.repository import Repository
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.formats import format_lined_list
from steward.helpers.keyboard import parse_and_validate_keyboard
from steward.helpers.pagination import (
    PageFormatContext,
    PaginationParseResult,
    Paginator,
    parse_pagination,
)


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
        if not validate_command_msg(update, ["fq", "featurerequest"]):
            return False

        assert (
            update.message.text
        )  # TODO: remove all asserts to message in chat() methods

        data = update.message.text.split(" ")
        if len(data) == 1 or data[1] == "list":
            return await self._get_paginator(FilterType.ALL).show_list(update)

        return await self._add_feature(
            update, update.message.text[len(data[0]) :].strip()
        )

    async def callback(self, update, context):
        assert update.callback_query.data

        filter_parsed = parse_and_validate_keyboard(
            "feature_request_filter",
            update.callback_query.data,
        )

        if filter_parsed is not None:
            return await self._get_paginator(
                FilterType(int(filter_parsed.metadata))
            ).process_parsed_callback(
                update,
                PaginationParseResult(
                    unique_keyboard_name="feature_request_list",
                    metadata=filter_parsed.metadata,
                    is_current_page=False,
                    page_number=0,
                ),
            )

        pagination_parsed = parse_and_validate_keyboard(
            "feature_request_list",
            update.callback_query.data,
            parse_func=parse_pagination,
        )

        if pagination_parsed is not None:
            return await self._get_paginator(
                FilterType(int(pagination_parsed.metadata))
            ).process_parsed_callback(
                update,
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
        await self.repository.save()
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
            lambda x: x.status == FeatureRequestStatus.DONE,
            lambda x: x.status == FeatureRequestStatus.DENIED,
            lambda x: x.status == FeatureRequestStatus.OPEN,
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
        # TODO: Может сделать описание в разных хендлерах, а потом для хинтов их объединять?
        # Сейчас просто при указании 2+ одинаковых команд будет показывать лишь первое описание
        return "/fq [done|deny|reopen <ids>] | [text] - управлять фича-реквестами"


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

            return await {
                "done": self._command(
                    [
                        "Фича-реквест уже выполнен",
                        "Фича-реквест уже отклонён",
                        None,
                    ],
                    FeatureRequestStatus.DONE,
                ),
                "deny": self._command(
                    [
                        "Фича-реквест уже выполнен",
                        "Фича-реквест уже отклонён",
                        None,
                    ],
                    FeatureRequestStatus.DENIED,
                ),
                "reopen": self._command(
                    [
                        None,
                        None,
                        "Фича-реквест и так открыт",
                    ],
                    FeatureRequestStatus.OPEN,
                ),
            }[data[1]](update, data[2:])

        return False

    def _command(
        self,
        error_list: list[str | None],
        new_status: FeatureRequestStatus,
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
                    update.message.from_user.id,
                    fq,
                    error_list,
                )

                if error is not None:
                    results.append((fq.id, error))
                    continue

                fq.history.append(
                    FeatureRequestChange(
                        author_id=update.message.from_user.id,
                        timestamp=datetime.datetime.now().timestamp(),
                        message_id=update.message.message_id,
                        status=new_status,
                    )
                )
                results.append((fq.id, None))

            await self.repository.save()

            results.sort(key=lambda x: x[1] is None)
            await update.message.reply_markdown(
                format_lined_list([
                    (id, "✅" if result is None else result) for id, result in results
                ])
            )

            return True

        return wrapper

    def _validate_fq(
        self,
        user_id: int,
        fq: FeatureRequest,
        messages: list[str | None],
    ):
        validation_statuses = [
            FeatureRequestStatus.DONE,
            FeatureRequestStatus.DENIED,
            FeatureRequestStatus.OPEN,
        ]

        for i, validation_status in enumerate(validation_statuses):
            if fq.status == validation_status and messages[i] is not None:
                return messages[i]

        if fq.author_id != user_id and not self.repository.is_admin(user_id):
            return "Вы не можете редактировать статус этого фича-реквеста"

        return None

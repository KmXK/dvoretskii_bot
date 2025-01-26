import datetime
import re
from enum import Enum
from typing import Optional

from telegram import InlineKeyboardButton, Update

from handlers.handler import Handler, validate_command_msg
from helpers.keyboard import (
    KeyboardParseResult,
    parse_and_validate_keyboard,
)
from helpers.pagination import (
    FormatItemContext,
    PaginationParseResult,
    Paginator,
    parse_pagination,
)
from models.feature_request import FeatureRequest
from repository import Repository


def format_fq(fq: FeatureRequest, format_context: FormatItemContext):
    return f"{format_context.item_number + 1:2}. `{fq.author_name}`: {re.sub('@[a-zA-Z0-9]+', lambda m: f'`{m.group(0)}`', fq.text)}"


class FilterType(Enum):
    ALL = 0
    DONE = 1
    DENIED = 2
    OPENED = 3


class FeatureRequestHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        if not validate_command_msg(update, "featurerequest"):
            return False

        data = update.message.text.split(" ")
        if len(data) == 1:
            return await self._get_paginator(FilterType.ALL).show_list(update)

        return await self._add_feature(
            update, update.message.text[len(data[0]) :].strip()
        )

    async def callback(self, update, context):
        print(update.callback_query.data)
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
                author_name=update.message.from_user.name,
                text=text,
                author_id=update.message.from_user.id,
                message_id=self.repository.db.feature_requests[-1].id + 1,
                chat_id=update.message.chat_id,
                creation_timestamp=datetime.datetime.now().timestamp(),
            )
        )
        self.repository.save()
        await update.message.reply_text("Фича-реквест добавлен")

    def _get_paginator(self, type: FilterType) -> Paginator:
        paginator = Paginator(
            unique_keyboard_name="feature_request_list",
            list_header="Фича реквесты",
            page_size=15,
            item_format_func=format_fq,
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

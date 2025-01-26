import datetime
import re

from telegram import InlineKeyboardButton, Update

from handlers.handler import Handler, validate_command_msg
from helpers.pagination import FormatItemContext, Paginator
from models.feature_request import FeatureRequest
from repository import Repository


def format_fq(fq: FeatureRequest, format_context: FormatItemContext):
    return f"{format_context.item_number + 1:2}. `{fq.author_name}`: {re.sub('@[a-zA-Z0-9]+', lambda m: f'`{m.group(0)}`', fq.text)}"


class FeatureRequestHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

        self.paginator = Paginator(
            unique_keyboard_name="feature_request_list",
            list_header="Фича реквесты",
            page_size=15,
            item_format_func=format_fq,
            data_func=lambda: self.repository.db.feature_requests,
            always_show_pagination=True,
        )

    async def chat(self, update, context):
        if not validate_command_msg(update, "featurerequest"):
            return False

        data = update.message.text.split(" ")
        if len(data) == 1:
            return await self.paginator.show_list(update)

        return await self._add_feature(
            update, update.message.text[len(data[0]):].strip()
        )

    async def callback(self, update, context):
        return await self.paginator.process_callback(update)

    def _create_filter_keyboard(self):
        return [
            InlineKeyboardButton("1", callback_data="1"),
            InlineKeyboardButton("2", callback_data="2"),
            InlineKeyboardButton("3", callback_data="3"),
        ]

    async def _add_feature(self, update: Update, text):
        self.repository.db.feature_requests.append(
            FeatureRequest(
                author_name=update.message.from_user.name,
                text=text,
                author_id=update.message.from_user.id,
                message_id=update.message.id,
                chat_id=update.message.chat_id,
                creation_timestamp=datetime.datetime.now().timestamp(),
            )
        )
        self.repository.save()
        await update.message.reply_text("Фича-реквест добавлен")

    def help(self):
        return "/featurerequest - посмотреть или добавить фича-реквест(ы)"

from telegram import Update
from handlers.handler import Handler, validate_command_msg
from models.feature_request import FeatureRequest
from repository import Repository
import re


def format_fq(index: int, fq: FeatureRequest):
    return f"{index+1:2}. `{fq.author_name}`: {re.sub('@[a-zA-Z0-9]+', lambda m: f'`{m.group(0)}`', fq.text)}"


class FeatureRequestHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        if not validate_command_msg(update, "featurerequest"):
            return False

        data = update.message.text.split(" ")
        if len(data) == 1:
            return await self._show_list(update)

        return await self._add_feature(
            update, update.message.text[len(data[0]) :].strip()
        )

    async def _show_list(self, update: Update):
        await update.message.reply_text(
            "Фича-реквесты:\n\n" +
            "\n".join(
                [
                    format_fq(i, fq)
                    for i, fq in enumerate(self.repository.db.feature_requests)
                ]
            ),
            parse_mode='markdown',
        )

    async def _add_feature(self, update: Update, text):
        self.repository.db.feature_requests.append(
            FeatureRequest(
                author_name=update.message.from_user.name,
                text=text,
                author_id=update.message.from_user.id,
            )
        )
        self.repository.save()
        await update.message.reply_text("Фича-реквест добавлен")

    def help(self):
        return '/featurerequest - посмотреть или добавить фича-реквест(ы)'

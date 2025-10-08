import datetime
import logging
from enum import Enum
from typing import Callable

import humanize.i18n
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import CallbackBotContext, ChatBotContext
from steward.data.models.army import Army
from steward.handlers.command_handler import CommandHandler, required
from steward.handlers.handler import Handler


def date_to_timestamp(date: str) -> float:
    return datetime.datetime.strptime(date.strip(), "%d.%m.%Y").timestamp()


humanize.i18n.activate("ru_RU")

logger = logging.getLogger(__name__)


@CommandHandler(
    "add_army",
    only_admin=True,
    arguments_template=r"(?P<name>.+) (?P<start_date>.+) (?P<end_date>.+)",
    arguments_mapping={
        "start_date": required(date_to_timestamp),
        "end_date": required(date_to_timestamp),
    },
)
class AddArmyHandler(Handler):
    async def chat(
        self, context: ChatBotContext, name: str, start_date: float, end_date: float
    ):
        self.repository.db.army.append(Army(name, start_date, end_date))
        await self.repository.save()
        await context.message.reply_markdown("Добавил человечка")

    def help(self):
        return "/add_army <name> <start_date> <end_date> - начать отслеживать срок человека в армии"


@CommandHandler("delete_army", only_admin=True, arguments_template=r"(?P<name>.+)")
class DeleteArmyHandler(Handler):
    async def chat(self, context: ChatBotContext, name: str):
        army_to_delete = next(
            (x for x in self.repository.db.army if x.name == name), None
        )

        if army_to_delete is None:
            await context.message.reply_text("Человечка с таким именем не существует")
        else:
            self.repository.db.army.remove(army_to_delete)
            await self.repository.save()
            await context.message.reply_markdown("Удалил человечка")

    def help(self):
        return "/delete_army <name> - перестать отслеживать срок человека в армии"


@CommandHandler("army", only_admin=False)
class ArmyHandler(Handler):
    class OutputType(Enum):
        HUMANIZE = "humanize"
        DAYS = "days"

    async def chat(self, context):
        if len(self.repository.db.army) == 0:
            await context.message.reply_markdown("В армейку никого не добавили")

        await self._get_list(
            ArmyHandler.OutputType.DAYS,
            lambda *args, **kwargs: context.message.reply_markdown(*args, **kwargs),
        )

    async def callback(self, context: CallbackBotContext):
        data = context.callback_query.data
        if data and len(data) > 0 and data.startswith("army_handler"):
            output_type = ArmyHandler.OutputType(data.split("|")[1])
            if output_type not in ArmyHandler.OutputType:
                output_type = ArmyHandler.OutputType.DAYS
        else:
            output_type = ArmyHandler.OutputType.DAYS

        assert context.update.effective_message
        await self._get_list(
            output_type,
            lambda *args, **kwargs: context.update.effective_message.edit_text(
                *args, **kwargs
            ),
        )

    async def _get_list(self, output_type: OutputType, send_func: Callable):
        army_list = [*self.repository.db.army]
        army_list.sort(key=lambda a: (a.end_date, a.start_date))

        text = ["Статус по армейке на сегодня:", ""]
        for army in army_list:
            last = (
                datetime.datetime.fromtimestamp(army.end_date) - datetime.datetime.now()
            )
            percent = 1 - last / (
                datetime.datetime.fromtimestamp(army.end_date)
                - datetime.datetime.fromtimestamp(army.start_date)
            )
            if last.total_seconds() > 0:
                if output_type == ArmyHandler.OutputType.DAYS:
                    text.append(
                        f"{army.name} - осталось {humanize.precisedelta(last, format='%0d', minimum_unit='hours', suppress=['years', 'months'])} ({percent * 100:.2f}%)"
                    )
                else:
                    text.append(
                        f"{army.name} - осталось {humanize.precisedelta(last, format='%0d', minimum_unit='hours')} ({percent * 100:.2f}%)"
                    )
            else:
                text.append(f"{army.name} - дембель")

        if output_type == ArmyHandler.OutputType.HUMANIZE:
            button_name = "Только дни"
            button_type = ArmyHandler.OutputType.DAYS
        elif output_type == ArmyHandler.OutputType.DAYS:
            button_name = "Месяцы + дни"
            button_type = ArmyHandler.OutputType.HUMANIZE

        try:
            await send_func(
                "\n".join(text),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=button_name,
                                callback_data=f"army_handler|{button_type.value}",
                            )
                        ]
                    ]
                ),
            )
        except telegram.error.BadRequest as e:
            logger.error(e)

    def help(self):
        return "/army - посмотреть статус армейцев"

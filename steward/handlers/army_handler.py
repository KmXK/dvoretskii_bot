import datetime
import logging

import humanize.i18n

from steward.bot.context import ChatBotContext
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
    async def chat(self, context):
        if len(self.repository.db.army) == 0:
            await context.message.reply_markdown("В армейку никого не добавили")
            return

        army_list = [*self.repository.db.army]
        army_list.sort(key=lambda a: (a.end_date, a.start_date))

        text = "Статус по армейке на сегодня: \n\n"
        for army in army_list:
            last = (
                datetime.datetime.fromtimestamp(army.end_date) - datetime.datetime.now()
            )
            percent = 1 - last / (
                datetime.datetime.fromtimestamp(army.end_date)
                - datetime.datetime.fromtimestamp(army.start_date)
            )
            if last.days > 0:
                text += f"{army.name} - осталось {humanize.precisedelta(last, format='%0.1f', minimum_unit='hours')} ({percent * 100:.5f}%)\n"
            else:
                text += f"{army.name} - дембель\n"
        await context.message.reply_markdown(text)

    def help(self):
        return "/army - посмотреть статус армейцев"

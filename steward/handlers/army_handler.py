import datetime
import logging

import humanize.i18n

from steward.data.models.army import Army
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


def date_to_timestamp(date: str) -> float:
    return datetime.datetime.strptime(date.strip(), "%d.%m.%Y").timestamp()


humanize.i18n.activate("ru_RU")

logger = logging.getLogger(__name__)


@CommandHandler("add_army", only_admin=True)
class AddArmyHandler(Handler):
    async def chat(self, context):
        try:
            name, start_date, end_date = (
                context.message.text.replace("/add_army", "").strip().split(" ")
            )
            if start_date is None or end_date is None:
                raise ValueError()
            self.repository.db.army.append(
                Army(
                    name=name.strip(),
                    start_date=date_to_timestamp(start_date),
                    end_date=date_to_timestamp(end_date),
                )
            )
            await self.repository.save()
            await context.message.reply_markdown("Добавил человечка")
        except ValueError as e:
            logger.exception(e)
            string = (
                "Ошибка. Добавление должно быть строкой, разделенной пробелом например: (Ваня 01.01.2022 01.01.2023) \n"
                "name - Имя \n"
                "start date - дата начало службы в формате дд.мм.гггг \n"
                "end date - дата конца службы в формате дд.мм.гггг \n"
            )
            await context.message.reply_text(string)

    def help(self):
        return "/add_army <name> <start_date> <end_date> - отслеживать срок человека в армии"


@CommandHandler("delete_army", only_admin=True)
class DeleteArmyHandler(Handler):
    async def chat(self, context):
        try:
            name = context.message.text.strip().replace("/delete_army", "").strip()
            army_to_delete = next(
                (x for x in self.repository.db.army if x.name == name), None
            )
            if army_to_delete is None:
                await context.message.reply_text(
                    "Человечка с таким именем не существует"
                )
            else:
                self.repository.db.army.remove(army_to_delete)
                await self.repository.save()
                await context.message.reply_markdown("Удалил человечка")
        except ValueError:
            await context.message.reply_text("Человечка с таким именем не существует")

    def help(self):
        return "/delete_army <name> - перестать отслеживать срок человека в армии"


@CommandHandler("army", only_admin=False)
class ArmyHandler(Handler):
    async def chat(self, context):
        if len(self.repository.db.army) == 0:
            await context.message.reply_markdown("В армейку никого не добавили")
            return

        text = "Статус по армейке на сегодня: \n\n"
        for army in self.repository.db.army:
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

import datetime
import logging

import humanize.i18n

from steward.data.models.army import Army
from steward.data.repository import Repository
from steward.handlers.handler import CommandHandler, Handler


def date_to_timestamp(date: str) -> float:
    return datetime.datetime.strptime(date.strip(), "%d.%m.%Y").timestamp()


humanize.i18n.activate("ru_RU")

logger = logging.getLogger(__name__)


@CommandHandler("add_army", only_admin=True)
class AddArmyHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            name, start_date, end_date = (
                update.message.text.replace("/add_army", "").strip().split(" ")
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
            self.repository.save()
            await update.message.reply_markdown("Добавил человечка")
        except ValueError as e:
            logger.exception(e)
            string = (
                "Ошибка. Добавление должно быть строкой, разделенной пробелом например: (Ваня 01.01.2022 01.01.2023) \n"
                "name - Имя \n"
                "start date - дата начало службы в формате дд.мм.гггг \n"
                "end date - дата конца службы в формате дд.мм.гггг \n"
            )
            await update.message.reply_text(string)

    def help(self):
        return "/add_army - отслеживать срок человека в армии"


@CommandHandler("delete_army", only_admin=True)
class DeleteArmyHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            name = update.message.text.strip().replace("/delete_army", "").strip()
            army_to_delete = next(
                (x for x in self.repository.db.army if x.name == name), None
            )
            if army_to_delete is None:
                await update.message.reply_text(
                    "Человечка с таким именем не существует"
                )
            else:
                self.repository.db.army.remove(army_to_delete)
                self.repository.save()
                await update.message.reply_markdown("Удалил человечка")
        except ValueError:
            await update.message.reply_text("Человечка с таким именем не существует")

    def help(self):
        return "/delete_army - перестать отслеживать срок человека в армии"


@CommandHandler("army", only_admin=False)
class ArmyHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        if len(self.repository.db.army) == 0:
            await update.message.reply_markdown("В армейку никого не добавили")
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
        await update.message.reply_markdown(text)

    def help(self):
        return "/army - посмотреть статус армейцев"

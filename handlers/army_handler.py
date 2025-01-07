import datetime
import json
import humanize
from handlers.handler import CommandHandler, Handler
from models.army import Army
from repository import Repository


def date_to_timestamp(date: str) -> float:
    return datetime.datetime.strptime(date.strip(), '%d.%m.%Y').timestamp()

humanize.i18n.activate("ru_RU")

@CommandHandler('add_army', only_admin=True)
class AddArmyHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            name, start_date, end_date = update.message.text.strip().replace('/add_army', '').split('%')
            if start_date == None or end_date == None:
                raise ValueError()
            self.repository.db.army.append(Army(name=name.strip(), start_date=start_date, end_date=end_date))
            self.repository.save()
            await update.message.reply_markdown(f'Добавил человечка')
        except ValueError:
            string = 'Ошибка. Добавление должно быть строкой, разделенной "," например: (Ваня,01.01.2022,01.01.2023) \n' \
                'name - Имя \n' \
                'date - дата в формате дд.мм.гггг \n'
            await update.message.reply_text(string)

    def help(self):
        return '/add_army name,start_datedate,end_date - отслеживать срок человека в армии'


@CommandHandler('delete_army', only_admin=True)
class DeleteArmyHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        try:
            name = update.message.text.strip().replace('/delete_army', '').strip()
            self.repository.db.army.remove(next((x for x in self.repository.db.army if x.name == name), None))
            self.repository.save()
            await update.message.reply_markdown('Удалил человечка')
        except ValueError:
            await update.message.reply_text('Человечка с таким именем не существует')

    def help(self):
        return '/delete_army name%date - перестать отслеживать срок человека в армии'


@CommandHandler('army', only_admin=True)
class ArmyHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        if len(self.repository.db.army) == 0:
            text += "В армейку никого не добавили"

        text = "Статус по армейке на сегодня: \n\n"
        for army in self.repository.db.army:
            last = datetime.datetime.fromtimestamp(army.end_date) - datetime.datetime.now()
            percent = 1 - last / (datetime.datetime.fromtimestamp(army.end_date) - datetime.datetime.fromtimestamp(army.start_date))
            if last.days > 0:
                text += f"{army.name} - осталось {humanize.naturaldelta(last)} (прошло {percent* 100:.5f}%)\n"
            else:
                text += f"{army.name} - дембель\n"
        await update.message.reply_markdown(text)

    def help(self):
        return '/army - посмотреть статус армейцев'
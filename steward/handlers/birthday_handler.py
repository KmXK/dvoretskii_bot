import logging
import re

from steward.bot.context import ChatBotContext
from steward.data.models.birthday import Birthday
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg

logger = logging.getLogger(__name__)

MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

ADD_PATTERN = re.compile(r"(.+)\s+(\d{1,2})\.(\d{1,2})")


@CommandHandler(
    "birthday",
    only_admin=True,
    arguments_template=r"remove (?P<name>.+)",
)
class BirthdayRemoveHandler(Handler):
    async def chat(self, context: ChatBotContext, name: str):
        chat_id = context.message.chat.id
        to_delete = next(
            (b for b in self.repository.db.birthdays
             if b.name == name and b.chat_id == chat_id),
            None,
        )

        if to_delete is None:
            await context.message.reply_text("Такого именинника нет в списке")
        else:
            self.repository.db.birthdays.remove(to_delete)
            await self.repository.save()
            await context.message.reply_markdown("Удалил именинника")

        return True

    def help(self):
        return None


class BirthdayViewHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "birthday"):
            return False

        assert context.message.text
        parts = context.message.text.split()

        if len(parts) > 1 and parts[1] == "remove":
            return False

        if len(parts) == 1:
            return await self._show_list(context)

        args = context.message.text[len(parts[0]):].strip()
        match = ADD_PATTERN.fullmatch(args)
        if not match:
            await context.message.reply_text("Формат: /birthday <имя> <ДД.ММ>")
            return True

        name = match.group(1).strip()
        day, month = int(match.group(2)), int(match.group(3))

        if not (1 <= day <= 31 and 1 <= month <= 12):
            await context.message.reply_text("Некорректная дата")
            return True

        chat_id = context.message.chat.id
        existing = next(
            (b for b in self.repository.db.birthdays
             if b.name == name and b.chat_id == chat_id),
            None,
        )
        if existing:
            existing.day = day
            existing.month = month
        else:
            self.repository.db.birthdays.append(Birthday(name, day, month, chat_id))

        await self.repository.save()
        await context.message.reply_markdown(
            f"Запомнил: {name} — {day} {MONTHS[month - 1]}"
        )
        return True

    async def _show_list(self, context: ChatBotContext):
        chat_id = context.message.chat.id
        chat_birthdays = [
            b for b in self.repository.db.birthdays if b.chat_id == chat_id
        ]

        if not chat_birthdays:
            await context.message.reply_markdown("Список именинников пуст")
            return True

        chat_birthdays.sort(key=lambda b: (b.month, b.day))

        lines = ["Дни рождения:", ""]
        for b in chat_birthdays:
            lines.append(f"{b.name} — {b.day} {MONTHS[b.month - 1]}")

        await context.message.reply_markdown("\n".join(lines))
        return True

    def help(self):
        return "/birthday [<name> <DD.MM>|remove <name>] — дни рождения"

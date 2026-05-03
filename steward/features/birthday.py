import re

from steward.data.models.birthday import Birthday
from steward.framework import Feature, FeatureContext, collection, subcommand


MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

ADD_PATTERN = re.compile(r"(?P<name>.+)\s+(?P<day>\d{1,2})\.(?P<month>\d{1,2})")


class BirthdayFeature(Feature):
    command = "birthday"
    description = "Дни рождения"

    birthdays = collection("birthdays")

    @subcommand("", description="Список именинников")
    async def view(self, ctx: FeatureContext):
        chat_id = ctx.chat_id
        items = sorted(
            (b for b in self.birthdays if b.chat_id == chat_id),
            key=lambda b: (b.month, b.day),
        )
        if not items:
            await ctx.reply("Список именинников пуст")
            return
        lines = ["Дни рождения:", ""]
        for b in items:
            lines.append(f"{b.name} — {b.day} {MONTHS[b.month - 1]}")
        await ctx.reply("\n".join(lines))

    @subcommand("remove <name:rest>", description="Удалить", admin=True)
    async def remove(self, ctx: FeatureContext, name: str):
        chat_id = ctx.chat_id
        item = self.birthdays.find_by(name=name, chat_id=chat_id)
        if item is None:
            await ctx.reply("Такого именинника нет в списке")
            return
        self.birthdays.remove(item)
        await self.birthdays.save()
        await ctx.reply("Удалил именинника")

    @subcommand("<args:rest>", description="Добавить именинника (<имя> <ДД.ММ>)", catchall=True)
    async def add(self, ctx: FeatureContext, args: str):
        m = ADD_PATTERN.fullmatch(args)
        if not m:
            await ctx.reply("Формат: /birthday <имя> <ДД.ММ>")
            return
        name = m.group("name").strip()
        day, month = int(m.group("day")), int(m.group("month"))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            await ctx.reply("Некорректная дата")
            return
        chat_id = ctx.chat_id
        existing = self.birthdays.find_by(name=name, chat_id=chat_id)
        if existing:
            existing.day = day
            existing.month = month
        else:
            self.birthdays.add(Birthday(name, day, month, chat_id))
        await self.birthdays.save()
        await ctx.reply(f"Запомнил: {name} — {day} {MONTHS[month - 1]}")

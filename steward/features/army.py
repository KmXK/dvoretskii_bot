import datetime
import logging
from enum import Enum

import humanize
import humanize.i18n
import telegram

from steward.data.models.army import Army
from steward.framework import (
    Button,
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    on_callback,
    subcommand,
)

humanize.i18n.activate("ru_RU")
logger = logging.getLogger(__name__)


def _date_to_timestamp(value: str) -> float:
    return datetime.datetime.strptime(value.strip(), "%d.%m.%Y").timestamp()


class _OutputType(str, Enum):
    HUMANIZE = "humanize"
    DAYS = "days"


class ArmyFeature(Feature):
    command = "army"
    description = "Управление армейцами"

    army = collection("army")

    @subcommand("", description="Список армейцев")
    async def view(self, ctx: FeatureContext):
        if not self.army.all():
            await ctx.reply("В армейку никого не добавили")
            return
        text, kb = self._render(_OutputType.DAYS)
        await ctx.reply(text, keyboard=kb)

    @subcommand("add <name:str> <start:str> <end:str>", description="Добавить армейца", admin=True)
    async def add(self, ctx: FeatureContext, name: str, start: str, end: str):
        try:
            start_ts = _date_to_timestamp(start)
            end_ts = _date_to_timestamp(end)
        except ValueError:
            await ctx.reply("Формат даты: ДД.ММ.ГГГГ")
            return
        self.army.add(Army(name, start_ts, end_ts))
        await self.army.save()
        await ctx.reply("Добавил человечка")

    @subcommand("remove <name:rest>", description="Удалить армейца", admin=True)
    async def remove(self, ctx: FeatureContext, name: str):
        item = self.army.find_by(name=name)
        if item is None:
            await ctx.reply("Человечка с таким именем не существует")
            return
        self.army.remove(item)
        await self.army.save()
        await ctx.reply("Удалил человечка")

    @on_callback("army:toggle", schema="<output:literal[days|humanize]>")
    async def on_toggle(self, ctx: FeatureContext, output: str):
        text, kb = self._render(_OutputType(output))
        try:
            await ctx.edit(text, keyboard=kb)
        except telegram.error.BadRequest as e:
            logger.error(e)

    def _render(self, output: _OutputType) -> tuple[str, Keyboard]:
        items = sorted(self.army.all(), key=lambda a: (a.end_date, a.start_date))
        lines = ["Статус по армейке на сегодня:", ""]
        now = datetime.datetime.now()
        for army in items:
            end = datetime.datetime.fromtimestamp(army.end_date)
            start = datetime.datetime.fromtimestamp(army.start_date)
            last = end - now
            percent = 1 - last / (end - start)
            if last.total_seconds() > 0:
                if output == _OutputType.DAYS:
                    pretty = humanize.precisedelta(
                        last, format="%0d", minimum_unit="hours",
                        suppress=["years", "months"],
                    )
                else:
                    pretty = humanize.precisedelta(
                        last, format="%0d", minimum_unit="hours",
                    )
                lines.append(f"{army.name} - осталось {pretty} ({percent * 100:.2f}%)")
            else:
                lines.append(f"{army.name} - дембель")

        if output == _OutputType.HUMANIZE:
            label, next_output = "Только дни", _OutputType.DAYS
        else:
            label, next_output = "Месяцы + дни", _OutputType.HUMANIZE

        kb = Keyboard.row(self.cb("army:toggle").button(label, output=next_output.value))
        return "\n".join(lines), kb

import datetime
import html as html_lib
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
        markdown = self._render_rich(_OutputType.DAYS)
        kb = self._toggle_kb(_OutputType.DAYS)
        try:
            await self._send_rich(ctx, markdown, kb)
        except telegram.error.TelegramError as e:
            # Если нативный sendRichMessage недоступен — отдаём <pre>-фолбэк,
            # который рендерится на любом клиенте и старом API.
            logger.error("sendRichMessage failed, fallback to <pre>: %s", e)
            text, fkb = self._render(_OutputType.DAYS)
            await ctx.reply(text, keyboard=fkb, html=True)

    @subcommand("add <name:str> <start:str> <end:str>", description="Добавить армейца")
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

    @subcommand("remove <name:rest>", description="Удалить армейца")
    async def remove(self, ctx: FeatureContext, name: str):
        item = self.army.find_by(name=name)
        if item is None:
            await ctx.reply("Человечка с таким именем не существует")
            return
        self.army.remove(item)
        await self.army.save()
        await ctx.reply("Удалил человечка")

    async def _send_rich(
        self, ctx: FeatureContext, markdown: str, keyboard: Keyboard | None = None
    ) -> None:
        """Шлёт нативную rich-таблицу через Bot API 10.1 sendRichMessage.

        Метода ещё нет в python-telegram-bot, поэтому дёргаем сырой эндпоинт.
        Контент передаётся как объект InputRichMessage в поле `rich_message`
        (проверено: top-level `markdown` отдаёт 400, вложенная форма — 200).
        Если reply_markup на rich-сообщениях не поддержан — шлём без кнопки,
        чтобы таблица в любом случае дошла.
        """
        api_kwargs: dict = {
            "chat_id": ctx.chat_id,
            "rich_message": {"markdown": markdown},
        }
        if keyboard is not None:
            try:
                await ctx.bot.do_api_request(
                    "sendRichMessage",
                    api_kwargs={**api_kwargs, "reply_markup": keyboard.to_markup().to_dict()},
                )
                return
            except telegram.error.BadRequest:
                logger.warning("sendRichMessage не принял reply_markup, шлю без кнопки")
        await ctx.bot.do_api_request("sendRichMessage", api_kwargs=api_kwargs)

    @on_callback("army:toggle", schema="<output:literal[days|humanize]>")
    async def on_toggle(self, ctx: FeatureContext, output: str):
        out = _OutputType(output)
        cq = ctx.callback_query
        if cq is None or cq.message is None:
            return
        api_kwargs: dict = {
            "chat_id": cq.message.chat.id,
            "message_id": cq.message.message_id,
            "rich_message": {"markdown": self._render_rich(out)},
            "reply_markup": self._toggle_kb(out).to_markup().to_dict(),
        }
        try:
            await ctx.bot.do_api_request("editMessageText", api_kwargs=api_kwargs)
        except telegram.error.BadRequest as e:
            # Фолбэк: сообщение было отправлено старым <pre>-путём.
            logger.error("editMessageText rich failed, fallback to <pre>: %s", e)
            text, kb = self._render(out)
            try:
                await ctx.edit(text, keyboard=kb, html=True)
            except telegram.error.BadRequest as e2:
                logger.error(e2)
        await ctx.toast()

    def _toggle_kb(self, output: _OutputType) -> Keyboard:
        if output == _OutputType.HUMANIZE:
            label, next_output = "Только дни", _OutputType.DAYS
        else:
            label, next_output = "Месяцы + дни", _OutputType.HUMANIZE
        return Keyboard.row(self.cb("army:toggle").button(label, output=next_output.value))

    def _compute_rows(self, output: _OutputType) -> list[tuple[str, str, str]]:
        items = sorted(self.army.all(), key=lambda a: (a.end_date, a.start_date))
        now = datetime.datetime.now()
        rows: list[tuple[str, str, str]] = []
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
                rows.append((army.name, pretty, f"{percent * 100:.1f}%"))
            else:
                rows.append((army.name, "дембель", "100%"))
        return rows

    def _render_rich(self, output: _OutputType) -> str:
        rows = self._compute_rows(output)

        def cell(value: str) -> str:
            return value.replace("|", "\\|")

        lines = [
            "# Статус по армейке на сегодня",
            "",
            "| Имя | Осталось | % |",
            "|:----|:---------|--:|",
        ]
        for name, pretty, percent in rows:
            lines.append(f"| **{cell(name)}** | {cell(pretty)} | {cell(percent)} |")
        return "\n".join(lines)

    def _render(self, output: _OutputType) -> tuple[str, Keyboard]:
        rows = self._compute_rows(output)
        table = _build_table(("Имя", "Осталось", "%"), rows)
        text = f"Статус по армейке на сегодня:\n{table}"
        return text, self._toggle_kb(output)


def _build_table(
    headers: tuple[str, ...], rows: list[tuple[str, ...]]
) -> str:
    """Render a fixed-width monospace table inside an HTML <pre> block.

    Это фолбэк для обычного parse_mode (Markdown/HTML), который таблицы не
    рендерит: выравниваем колонки пробелами и заворачиваем в <pre> — выглядит
    одинаково на всех клиентах. Настоящую таблицу даёт только `/army rich`
    через sendRichMessage (Bot API 10.1).
    """
    n = len(headers)
    widths = [len(headers[i]) for i in range(n)]
    for row in rows:
        for i in range(n):
            widths[i] = max(widths[i], len(row[i]))

    def fmt(cells: tuple[str, ...]) -> str:
        return "  ".join(cells[i].ljust(widths[i]) for i in range(n)).rstrip()

    lines = [fmt(headers), "  ".join("-" * widths[i] for i in range(n))]
    lines.extend(fmt(row) for row in rows)
    body = html_lib.escape("\n".join(lines))
    return f"<pre>{body}</pre>"

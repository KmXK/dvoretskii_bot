import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import ChatBotContext
from steward.delayed_action.reminder import CompletedReminder, ReminderDelayedAction, ReminderGenerator
from steward.handlers.command_handler import CommandHandler, required
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.keyboard import parse_and_validate_keyboard

TZ = ZoneInfo("Europe/Minsk")
INTERVAL_PATTERN = re.compile(r'^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$')
TIME_PATTERN = re.compile(r'^(\d{1,2}):(\d{2})$')
DATE_TIME_PATTERN = re.compile(r'^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s+(\d{1,2}):(\d{2})$')
REPEAT_PATTERN = re.compile(r'^x(\d+|\*)$')


def parse_interval(s: str) -> timedelta | None:
    match = INTERVAL_PATTERN.match(s)
    if not match:
        return None
    d, h, m, sec = match.groups()
    total = timedelta(days=int(d or 0), hours=int(h or 0), minutes=int(m or 0), seconds=int(sec or 0))
    return total if total.total_seconds() > 0 else None


def parse_time_today(s: str) -> datetime | None:
    match = TIME_PATTERN.match(s)
    if not match:
        return None
    h, m = int(match.group(1)), int(match.group(2))
    now = datetime.now(TZ)
    dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if dt <= now:
        dt += timedelta(days=1)
    return dt


def parse_date_time(s: str) -> datetime | None:
    match = DATE_TIME_PATTERN.match(s)
    if not match:
        return None
    day, month, year, h, m = match.groups()
    now = datetime.now(TZ)
    year = int(year) if year else now.year
    if year < 100:
        year += 2000
    return datetime(year, int(month), int(day), int(h), int(m), tzinfo=TZ)


def parse_repeat(s: str) -> int | None:
    match = REPEAT_PATTERN.match(s)
    if not match:
        return None
    val = match.group(1)
    return None if val == "*" else int(val)


def format_interval(seconds: int) -> str:
    if seconds >= 86400 and seconds % 86400 == 0:
        d = seconds // 86400
        return f"{d}d" if d > 1 else "1d"
    if seconds >= 3600 and seconds % 3600 == 0:
        h = seconds // 3600
        return f"{h}h" if h > 1 else "1h"
    if seconds >= 60 and seconds % 60 == 0:
        m = seconds // 60
        return f"{m}m" if m > 1 else "1m"
    return f"{seconds}s"


def format_reminder(r: ReminderDelayedAction) -> str:
    gen = r.generator
    time_str = gen.next_fire.astimezone(TZ).strftime("%d.%m %H:%M")
    repeat_str = ""
    if gen.interval_seconds:
        interval_str = format_interval(gen.interval_seconds)
        if gen.repeat_remaining is None:
            repeat_str = f" (∞ каждые {interval_str})"
        else:
            repeat_str = f" (x{gen.repeat_remaining} каждые {interval_str})"
    return f"`{r.id}` {time_str}{repeat_str} — {r.text}"


def format_completed(r: CompletedReminder) -> str:
    time_str = r.completed_at.astimezone(TZ).strftime("%d.%m %H:%M")
    count_str = f" (x{r.fired_count})" if r.fired_count > 1 else ""
    return f"`{r.id}` {time_str}{count_str} — {r.text}"


@CommandHandler("remind", arguments_template=r"(?P<args>.+)?", arguments_mapping={"args": lambda x: x or ""})
class RemindAddHandler(Handler):
    async def chat(self, context: ChatBotContext, args: str):
        if not args.strip():
            await context.message.reply_text(
                "Использование:\n"
                "/remind <время> [x<кол-во>] <текст>\n\n"
                "Примеры времени: 10m, 2h30m, 15:30, 25.12 10:00\n"
                "Повторение: x3 (3 раза), x* (бесконечно)\n\n"
                "Управление:\n"
                "/remind remove <id>\n"
                "/remind edit <id> <новый текст>\n"
                "/reminders — список"
            )
            return True

        parts = args.split()
        if parts[0] in ("remove", "edit", "list"):
            return False

        if len(parts) < 2:
            await context.message.reply_text("Укажи время и текст напоминания")
            return True

        next_fire = None
        interval_seconds = None
        repeat_count = None
        text_start = 1

        if interval := parse_interval(parts[0]):
            next_fire = datetime.now(timezone.utc) + interval
            interval_seconds = int(interval.total_seconds())
        elif dt := parse_time_today(parts[0]):
            next_fire = dt.astimezone(timezone.utc)
            interval_seconds = 24 * 60 * 60
        elif len(parts) >= 2:
            combined = f"{parts[0]} {parts[1]}"
            if dt := parse_date_time(combined):
                next_fire = dt.astimezone(timezone.utc)
                text_start = 2

        if not next_fire:
            await context.message.reply_text("Не могу распознать время. Примеры: 10m, 2h30m, 15:30, 25.12 10:00")
            return True

        has_repeat = False
        if len(parts) > text_start and parts[text_start].startswith("x"):
            has_repeat = True
            repeat_count = parse_repeat(parts[text_start])
            text_start += 1
            if not interval_seconds:
                await context.message.reply_text("Повторение работает только с интервалом или временем (10m, 1h, 15:30...)")
                return True

        text = " ".join(parts[text_start:])
        if not text:
            await context.message.reply_text("Укажи текст напоминания")
            return True

        reminder = ReminderDelayedAction(
            id=str(uuid.uuid4())[:8],
            chat_id=context.message.chat_id,
            user_id=context.message.from_user.id,
            text=text,
            created_at=datetime.now(timezone.utc),
            generator=ReminderGenerator(
                next_fire=next_fire,
                interval_seconds=interval_seconds if has_repeat else None,
                repeat_remaining=repeat_count,
            ),
        )

        self.repository.db.delayed_actions.append(reminder)
        await self.repository.save()

        time_str = next_fire.astimezone(TZ).strftime("%d.%m.%Y %H:%M")
        repeat_str = ""
        if has_repeat:
            if repeat_count is None:
                repeat_str = " (∞)"
            else:
                repeat_str = f" (x{repeat_count})"

        await context.message.reply_text(f"✅ `{reminder.id}` на {time_str}{repeat_str}", parse_mode="markdown")
        return True

    def help(self) -> str | None:
        return "/remind <время> [x<кол-во>] <текст> - создать напоминание"


@CommandHandler("remind", arguments_template=r"remove (?P<id>\S+)")
class RemindRemoveHandler(Handler):
    async def chat(self, context: ChatBotContext, id: str):
        chat_id = context.message.chat_id
        reminder = next(
            (a for a in self.repository.db.delayed_actions
             if isinstance(a, ReminderDelayedAction) and a.id == id and a.chat_id == chat_id),
            None
        )

        if not reminder:
            await context.message.reply_text("Напоминание не найдено")
            return True

        self.repository.db.delayed_actions.remove(reminder)
        await self.repository.save()
        await context.message.reply_text(f"🗑 Удалено: {reminder.text}")
        return True

    def help(self) -> str | None:
        return None


@CommandHandler("remind", arguments_template=r"edit (?P<id>\S+) (?P<new_text>.+)")
class RemindEditHandler(Handler):
    async def chat(self, context: ChatBotContext, id: str, new_text: str):
        chat_id = context.message.chat_id
        reminder = next(
            (a for a in self.repository.db.delayed_actions
             if isinstance(a, ReminderDelayedAction) and a.id == id and a.chat_id == chat_id),
            None
        )

        if not reminder:
            await context.message.reply_text("Напоминание не найдено")
            return True

        old_text = reminder.text
        reminder.text = new_text
        await self.repository.save()
        await context.message.reply_text(f"✏️ Изменено:\n{old_text} → {new_text}")
        return True

    def help(self) -> str | None:
        return None


class RemindersHandler(Handler):
    KEYBOARD_NAME = "reminders"

    def _get_active(self, chat_id: int) -> list[ReminderDelayedAction]:
        items = [a for a in self.repository.db.delayed_actions
                 if isinstance(a, ReminderDelayedAction) and a.chat_id == chat_id]
        return sorted(items, key=lambda r: r.generator.next_fire)

    def _get_completed(self, chat_id: int) -> list[CompletedReminder]:
        return sorted(
            [r for r in self.repository.db.completed_reminders if r.chat_id == chat_id],
            key=lambda r: r.completed_at,
            reverse=True,
        )[:50]

    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "reminders"):
            if not validate_command_msg(context.update, "remind"):
                return False
            parts = context.message.text.split()
            if len(parts) < 2 or parts[1] != "list":
                return False

        chat_id = context.message.chat_id
        active = self._get_active(chat_id)

        if not active and not self._get_completed(chat_id):
            await context.message.reply_text("Напоминаний нет")
            return True

        text = self._format_active_list(active)
        keyboard = self._build_keyboard("active", 0, len(active))
        await context.message.reply_text(text, reply_markup=keyboard, parse_mode="markdown")
        return True

    async def callback(self, context: ChatBotContext):
        query = context.update.callback_query
        if not query or not query.data:
            return False

        parsed = parse_and_validate_keyboard(self.KEYBOARD_NAME, query.data)
        if not parsed:
            return False

        await query.answer()

        parts = parsed.metadata.split(":")
        mode = parts[0]
        page = int(parts[1]) if len(parts) > 1 else 0
        chat_id = query.message.chat_id

        if mode == "active":
            items = self._get_active(chat_id)
            text = self._format_active_list(items, page)
        else:
            items = self._get_completed(chat_id)
            text = self._format_completed_list(items, page)

        keyboard = self._build_keyboard(mode, page, len(items))
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode="markdown")
        return True

    def _format_active_list(self, items: list[ReminderDelayedAction], page: int = 0) -> str:
        if not items:
            return "📋 *Активные напоминания*\n\nСписок пуст"
        page_size = 10
        start = page * page_size
        end = start + page_size
        lines = [format_reminder(r) for r in items[start:end]]
        return "📋 *Активные напоминания*\n\n" + "\n".join(lines)

    def _format_completed_list(self, items: list[CompletedReminder], page: int = 0) -> str:
        if not items:
            return "✅ *Завершённые напоминания*\n\nСписок пуст"
        page_size = 10
        start = page * page_size
        end = start + page_size
        lines = [format_completed(r) for r in items[start:end]]
        return "✅ *Завершённые напоминания*\n\n" + "\n".join(lines)

    def _build_keyboard(self, mode: str, page: int, total: int) -> InlineKeyboardMarkup:
        page_size = 10
        max_page = max(0, (total - 1) // page_size)

        rows = []
        if max_page > 0:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("<", callback_data=f"{self.KEYBOARD_NAME}|{mode}:{page - 1}"))
            nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{max_page + 1}", callback_data=f"{self.KEYBOARD_NAME}|{mode}:{page}"))
            if page < max_page:
                nav_buttons.append(InlineKeyboardButton(">", callback_data=f"{self.KEYBOARD_NAME}|{mode}:{page + 1}"))
            rows.append(nav_buttons)

        switch_text = "✅ Завершённые" if mode == "active" else "📋 Активные"
        switch_mode = "completed" if mode == "active" else "active"
        rows.append([InlineKeyboardButton(switch_text, callback_data=f"{self.KEYBOARD_NAME}|{switch_mode}:0")])

        return InlineKeyboardMarkup(rows)

    def help(self) -> str | None:
        return "/reminders - список напоминаний"

import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from steward.delayed_action.reminder import (
    CompletedReminder,
    ReminderDelayedAction,
    ReminderGenerator,
)
from steward.framework import (
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    paginated,
    subcommand,
)
from steward.helpers.command_validation import ValidationArgumentsError

_TZ = ZoneInfo("Europe/Minsk")
_INTERVAL_RE = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATE_TIME_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s+(\d{1,2}):(\d{2})$")
_REPEAT_RE = re.compile(r"^x(\d+|\*)$")


def _parse_interval(s: str) -> timedelta | None:
    m = _INTERVAL_RE.match(s)
    if not m:
        return None
    d, h, mi, sec = m.groups()
    total = timedelta(days=int(d or 0), hours=int(h or 0), minutes=int(mi or 0), seconds=int(sec or 0))
    return total if total.total_seconds() > 0 else None


def _parse_time_today(s: str) -> datetime | None:
    m = _TIME_RE.match(s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    now = datetime.now(_TZ)
    dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if dt <= now:
        dt += timedelta(days=1)
    return dt


def _parse_date_time(s: str) -> datetime | None:
    m = _DATE_TIME_RE.match(s)
    if not m:
        return None
    day, month, year, h, mi = m.groups()
    now = datetime.now(_TZ)
    year = int(year) if year else now.year
    if year < 100:
        year += 2000
    return datetime(year, int(month), int(day), int(h), int(mi), tzinfo=_TZ)


def _parse_repeat(s: str) -> int | None:
    m = _REPEAT_RE.match(s)
    if not m:
        return None
    val = m.group(1)
    return None if val == "*" else int(val)


_DAY_NAMES: dict[str, int | list[int]] = {
    "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "weekday": [0, 1, 2, 3, 4], "weekend": [5, 6],
}
_DAY_NAMES_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _parse_days(s: str) -> list[int] | None:
    s = s.lower()
    if s in _DAY_NAMES:
        val = _DAY_NAMES[s]
        return val if isinstance(val, list) else [val]
    days = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            si = _DAY_NAMES.get(start.strip())
            ei = _DAY_NAMES.get(end.strip())
            if si is None or ei is None or isinstance(si, list) or isinstance(ei, list):
                return None
            if si <= ei:
                days.update(range(si, ei + 1))
            else:
                days.update(range(si, 7))
                days.update(range(0, ei + 1))
        else:
            idx = _DAY_NAMES.get(part)
            if idx is None or isinstance(idx, list):
                return None
            days.add(idx)
    return sorted(days) if days else None


def _format_days(days: list[int]) -> str:
    if not days:
        return ""
    if days == [0, 1, 2, 3, 4]:
        return "пн-пт"
    if days == [5, 6]:
        return "сб-вс"
    if days == [0, 1, 2, 3, 4, 5, 6]:
        return ""
    ranges = []
    start = days[0]
    end = days[0]
    for d in days[1:]:
        if d == end + 1:
            end = d
        else:
            ranges.append((start, end))
            start = end = d
    ranges.append((start, end))
    parts = []
    for s, e in ranges:
        if s == e:
            parts.append(_DAY_NAMES_SHORT[s])
        elif e - s == 1:
            parts.append(f"{_DAY_NAMES_SHORT[s]},{_DAY_NAMES_SHORT[e]}")
        else:
            parts.append(f"{_DAY_NAMES_SHORT[s]}-{_DAY_NAMES_SHORT[e]}")
    return ",".join(parts)


def _format_interval(seconds: int) -> str:
    if seconds >= 86400 and seconds % 86400 == 0:
        d = seconds // 86400
        return f"{d}d" if d > 1 else "1d"
    if seconds >= 3600 and seconds % 3600 == 0:
        h = seconds // 3600
        return f"{h}h" if h > 1 else "1h"
    if seconds >= 60 and seconds % 60 == 0:
        mi = seconds // 60
        return f"{mi}m" if mi > 1 else "1m"
    return f"{seconds}s"


def _format_reminder(r: ReminderDelayedAction) -> str:
    gen = r.generator
    time_str = gen.next_fire.astimezone(_TZ).strftime("%d.%m %H:%M")
    repeat_str = ""
    if gen.interval_seconds:
        interval_str = _format_interval(gen.interval_seconds)
        days_str = _format_days(gen.days) if gen.days else ""
        days_str = f" {days_str}" if days_str else ""
        if gen.repeat_remaining is None:
            repeat_str = f" (∞ каждые {interval_str}{days_str})"
        else:
            repeat_str = f" (x{gen.repeat_remaining} каждые {interval_str}{days_str})"
    return f"`{r.id}` {time_str}{repeat_str} — {r.text}"


def _format_completed(r: CompletedReminder) -> str:
    time_str = r.completed_at.astimezone(_TZ).strftime("%d.%m %H:%M")
    count_str = f" (x{r.fired_count})" if r.fired_count > 1 else ""
    return f"`{r.id}` {time_str}{count_str} — {r.text}"


class RemindFeature(Feature):
    command = "remind"
    description = "Создание напоминаний"
    help_examples = [
        "«напомни через 10 минут позвонить» → /remind 10m позвонить",
        "«каждый понедельник в 9 утра намаз» → /remind 9:00 x* пн намаз",
        "«каждый день в 22:00 выпить воду» → /remind 22:00 x* выпить воду",
    ]

    delayed_actions = collection("delayed_actions")
    completed_reminders = collection("completed_reminders")

    @subcommand("", description="Подсказка по использованию")
    async def usage(self, ctx: FeatureContext):
        await ctx.reply(
            "Использование:\n"
            "/remind <время> [x<кол-во>] [дни] <текст>\n\n"
            "Примеры времени: 10m, 2h30m, 15:30, 25.12 10:00\n"
            "Повторение: x3 (3 раза), x* (бесконечно)\n"
            "Дни: weekday, weekend, пн-пт, пн,ср,пт\n\n"
            "Управление:\n"
            "/remind remove <id>\n"
            "/remind edit <id> <новый текст>\n"
            "/reminders — список"
        )

    @subcommand("list", description="Список")
    async def list_(self, ctx: FeatureContext):
        await self._show_list(ctx)

    @subcommand("remove <id:str>", description="Удалить")
    async def remove(self, ctx: FeatureContext, id: str):
        chat_id = ctx.chat_id
        reminder = self.delayed_actions.find_one(
            lambda a: isinstance(a, ReminderDelayedAction) and a.id == id and a.chat_id == chat_id
        )
        if not reminder:
            await ctx.reply("Напоминание не найдено")
            return
        self.delayed_actions.remove(reminder)
        await self.delayed_actions.save()
        await ctx.reply(f"🗑 Удалено: {reminder.text}")

    @subcommand("edit <id:str> <new_text:rest>", description="Изменить текст")
    async def edit(self, ctx: FeatureContext, id: str, new_text: str):
        chat_id = ctx.chat_id
        reminder = self.delayed_actions.find_one(
            lambda a: isinstance(a, ReminderDelayedAction) and a.id == id and a.chat_id == chat_id
        )
        if not reminder:
            await ctx.reply("Напоминание не найдено")
            return
        old_text = reminder.text
        reminder.text = new_text
        await self.delayed_actions.save()
        await ctx.reply(f"✏️ Изменено:\n{old_text} → {new_text}")

    @subcommand("<args:rest>", description="Создать напоминание", catchall=True)
    async def add(self, ctx: FeatureContext, args: str):
        if not args.strip():
            raise ValidationArgumentsError()
        parts = args.split()
        if parts[0] in ("remove", "edit", "list"):
            return False
        if len(parts) < 2:
            await ctx.reply("Укажи время и текст напоминания")
            return
        next_fire = None
        interval_seconds = None
        repeat_count = None
        text_start = 1
        if interval := _parse_interval(parts[0]):
            next_fire = datetime.now(timezone.utc) + interval
            interval_seconds = int(interval.total_seconds())
        elif dt := _parse_time_today(parts[0]):
            next_fire = dt.astimezone(timezone.utc)
            interval_seconds = 24 * 60 * 60
        elif len(parts) >= 2:
            combined = f"{parts[0]} {parts[1]}"
            if dt := _parse_date_time(combined):
                next_fire = dt.astimezone(timezone.utc)
                text_start = 2
        if not next_fire:
            await ctx.reply("Не могу распознать время. Примеры: 10m, 2h30m, 15:30, 25.12 10:00")
            return

        has_repeat = False
        days = None
        while len(parts) > text_start:
            if parts[text_start].startswith("x"):
                has_repeat = True
                repeat_count = _parse_repeat(parts[text_start])
                text_start += 1
                if not interval_seconds:
                    await ctx.reply("Повторение работает только с интервалом или временем (10m, 1h, 15:30...)")
                    return
            elif parsed_days := _parse_days(parts[text_start]):
                days = parsed_days
                has_repeat = True
                text_start += 1
            else:
                break

        if days and not interval_seconds:
            await ctx.reply("Дни работают только с интервалом или временем (10m, 1h, 15:30...)")
            return

        text = " ".join(parts[text_start:])
        if not text:
            await ctx.reply("Укажи текст напоминания")
            return

        generator = ReminderGenerator(
            next_fire=next_fire,
            interval_seconds=interval_seconds if has_repeat else None,
            repeat_remaining=repeat_count,
            days=days,
        )
        generator.skip_to_allowed_day()

        reminder = ReminderDelayedAction(
            id=str(uuid.uuid4())[:8],
            chat_id=ctx.chat_id,
            user_id=ctx.user_id,
            text=text,
            created_at=datetime.now(timezone.utc),
            generator=generator,
        )
        self.delayed_actions.add(reminder)
        await self.delayed_actions.save()
        time_str = next_fire.astimezone(_TZ).strftime("%d.%m.%Y %H:%M")
        repeat_str = ""
        if has_repeat:
            repeat_str = " (∞)" if repeat_count is None else f" (x{repeat_count})"
        await ctx.reply(f"✅ `{reminder.id}` на {time_str}{repeat_str}")

    @paginated("reminders", per_page=10)
    def reminders_page(self, ctx: FeatureContext, metadata: str):
        chat_id = ctx.chat_id
        if metadata == "completed":
            items = [r for r in self.completed_reminders if r.chat_id == chat_id]
            items.sort(key=lambda r: r.completed_at, reverse=True)
            items = items[:50]
            header = "✅ *Завершённые напоминания*"
            switch = "📋 Активные"
            switch_meta = "active"
            render = lambda batch: header + "\n\n" + "\n".join(_format_completed(r) for r in batch)
        else:
            items = [
                a for a in self.delayed_actions
                if isinstance(a, ReminderDelayedAction) and a.chat_id == chat_id
            ]
            items.sort(key=lambda r: r.generator.next_fire)
            header = "📋 *Активные напоминания*"
            switch = "✅ Завершённые"
            switch_meta = "completed"
            render = lambda batch: header + "\n\n" + "\n".join(_format_reminder(r) for r in batch)
        extra = Keyboard.row(
            self.page_button("reminders", switch, metadata=switch_meta, page=0)
        )
        return items, render, extra

    async def _show_list(self, ctx: FeatureContext):
        chat_id = ctx.chat_id
        active = [
            a for a in self.delayed_actions
            if isinstance(a, ReminderDelayedAction) and a.chat_id == chat_id
        ]
        completed = [r for r in self.completed_reminders if r.chat_id == chat_id]
        if not active and not completed:
            await ctx.reply("Напоминаний нет")
            return
        await self.paginate(ctx, "reminders", metadata="active")


class RemindersFeature(Feature):
    command = "reminders"
    description = "Список напоминаний"

    delayed_actions = collection("delayed_actions")
    completed_reminders = collection("completed_reminders")

    def __init__(self):
        super().__init__()
        self._proxy: RemindFeature | None = None

    @subcommand("", description="Список")
    async def list_(self, ctx: FeatureContext):
        if self._proxy is None:
            self._proxy = RemindFeature()
            self._proxy.repository = self.repository
            self._proxy.bot = self.bot
        await self._proxy._show_list(ctx)

import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler

OFFSET_RE = re.compile(r"[+-]?\d{1,2}(?::(?:00|30|45))?")

CITY_TIMEZONES: dict[str, str] = {
    "москва": "Europe/Moscow",
    "санкт-петербург": "Europe/Moscow",
    "петербург": "Europe/Moscow",
    "питер": "Europe/Moscow",
    "новосибирск": "Asia/Novosibirsk",
    "екатеринбург": "Asia/Yekaterinburg",
    "казань": "Europe/Moscow",
    "красноярск": "Asia/Krasnoyarsk",
    "самара": "Europe/Samara",
    "омск": "Asia/Omsk",
    "уфа": "Asia/Yekaterinburg",
    "пермь": "Asia/Yekaterinburg",
    "волгоград": "Europe/Volgograd",
    "владивосток": "Asia/Vladivostok",
    "хабаровск": "Asia/Vladivostok",
    "иркутск": "Asia/Irkutsk",
    "калининград": "Europe/Kaliningrad",
    "киев": "Europe/Kyiv",
    "минск": "Europe/Minsk",
    "алматы": "Asia/Almaty",
    "ташкент": "Asia/Tashkent",
    "тбилиси": "Asia/Tbilisi",
    "баку": "Asia/Baku",
    "ереван": "Asia/Yerevan",
    "london": "Europe/London",
    "лондон": "Europe/London",
    "new york": "America/New_York",
    "нью-йорк": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "лос-анджелес": "America/Los_Angeles",
    "tokyo": "Asia/Tokyo",
    "токио": "Asia/Tokyo",
    "beijing": "Asia/Shanghai",
    "пекин": "Asia/Shanghai",
    "dubai": "Asia/Dubai",
    "дубай": "Asia/Dubai",
    "paris": "Europe/Paris",
    "париж": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "берлин": "Europe/Berlin",
    "istanbul": "Europe/Istanbul",
    "стамбул": "Europe/Istanbul",
    "bangkok": "Asia/Bangkok",
    "бангкок": "Asia/Bangkok",
    "singapore": "Asia/Singapore",
    "сингапур": "Asia/Singapore",
    "seoul": "Asia/Seoul",
    "сеул": "Asia/Seoul",
    "sydney": "Australia/Sydney",
    "сидней": "Australia/Sydney",
    "toronto": "America/Toronto",
    "торонто": "America/Toronto",
    "mumbai": "Asia/Kolkata",
    "мумбаи": "Asia/Kolkata",
    "cairo": "Africa/Cairo",
    "каир": "Africa/Cairo",
    "rome": "Europe/Rome",
    "рим": "Europe/Rome",
    "madrid": "Europe/Madrid",
    "мадрид": "Europe/Madrid",
    "amsterdam": "Europe/Amsterdam",
    "амстердам": "Europe/Amsterdam",
    "warsaw": "Europe/Warsaw",
    "варшава": "Europe/Warsaw",
    "prague": "Europe/Prague",
    "прага": "Europe/Prague",
    "vienna": "Europe/Vienna",
    "вена": "Europe/Vienna",
    "helsinki": "Europe/Helsinki",
    "хельсинки": "Europe/Helsinki",
    "lisbon": "Europe/Lisbon",
    "лиссабон": "Europe/Lisbon",
    "athens": "Europe/Athens",
    "афины": "Europe/Athens",
    "chicago": "America/Chicago",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "mexico city": "America/Mexico_City",
    "hong kong": "Asia/Hong_Kong",
    "гонконг": "Asia/Hong_Kong",
    "jakarta": "Asia/Jakarta",
    "джакарта": "Asia/Jakarta",
    "tehran": "Asia/Tehran",
    "тегеран": "Asia/Tehran",
    "riyadh": "Asia/Riyadh",
    "эр-рияд": "Asia/Riyadh",
    "auckland": "Pacific/Auckland",
    "окленд": "Pacific/Auckland",
}


def _format_offset(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


def _format_time(dt: datetime, label: str) -> str:
    offset_str = _format_offset(dt.utcoffset())
    return f"🕐 <b>{label}</b>\n{dt.strftime('%d.%m.%Y %H:%M:%S')} ({offset_str})"


def _time_by_offset(offset_str: str) -> str | None:
    offset_str = offset_str.strip()
    if ":" in offset_str:
        parts = offset_str.replace("+", "").split(":")
        hours, minutes = int(parts[0]), int(parts[1])
        if hours < 0:
            minutes = -minutes
    else:
        hours = int(offset_str)
        minutes = 0

    if not (-12 <= hours <= 14):
        return None

    tz = timezone(timedelta(hours=hours, minutes=minutes))
    now = datetime.now(tz)
    return _format_time(now, _format_offset(tz.utcoffset(None)))


def _time_by_city(city: str) -> str | None:
    tz_name = CITY_TIMEZONES.get(city.lower())
    if tz_name is None:
        return None
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    return _format_time(now, f"{city.title()} ({tz_name})")


@CommandHandler("timezone", arguments_template=r"(?P<query>.+)?")
class TimezoneHandler(Handler):
    async def chat(self, context: ChatBotContext, query: str = None):
        if not query:
            now = datetime.now(timezone.utc)
            await context.message.reply_html(_format_time(now, "UTC"))
            return True

        query = query.strip()

        if OFFSET_RE.fullmatch(query):
            result = _time_by_offset(query)
            if result is None:
                await context.message.reply_text("Некорректное смещение (от -12 до +14)")
                return True
            await context.message.reply_html(result)
            return True

        result = _time_by_city(query)
        if result is None:
            await context.message.reply_text(f"Город «{query}» не найден")
            return True

        await context.message.reply_html(result)
        return True

    def help(self):
        return (
            "/timezone - текущее время UTC\n"
            "/timezone +5 - время в UTC+5\n"
            "/timezone москва - время по городу"
        )

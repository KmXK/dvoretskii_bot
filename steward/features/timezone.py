import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from steward.framework import Feature, FeatureContext, subcommand


_OFFSET_RE = re.compile(r"[+-]?\d{1,2}(?::(?:00|30|45))?")

_CITY_TIMEZONES: dict[str, str] = {
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
    total = int(td.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


def _format_time(dt: datetime, label: str) -> str:
    offset_str = _format_offset(dt.utcoffset())
    return f"🕐 <b>{label}</b>\n{dt.strftime('%d.%m.%Y %H:%M:%S')} ({offset_str})"


def _time_by_offset(offset_str: str) -> str | None:
    s = offset_str.strip()
    if ":" in s:
        parts = s.replace("+", "").split(":")
        hours, minutes = int(parts[0]), int(parts[1])
        if hours < 0:
            minutes = -minutes
    else:
        hours = int(s)
        minutes = 0
    if not (-12 <= hours <= 14):
        return None
    tz = timezone(timedelta(hours=hours, minutes=minutes))
    return _format_time(datetime.now(tz), _format_offset(tz.utcoffset(None)))


def _time_by_city(city: str) -> str | None:
    name = _CITY_TIMEZONES.get(city.lower())
    if name is None:
        return None
    tz = ZoneInfo(name)
    return _format_time(datetime.now(tz), f"{city.title()} ({name})")


class TimezoneFeature(Feature):
    command = "timezone"
    description = "Время в часовых поясах"
    help_examples = [
        "«сколько времени в Москве» → /timezone москва",
        "«время UTC+5» → /timezone +5",
    ]

    @subcommand("", description="Текущее UTC")
    async def utc(self, ctx: FeatureContext):
        await ctx.reply(_format_time(datetime.now(timezone.utc), "UTC"), html=True, markdown=False)

    @subcommand("<query:rest>", description="По смещению (+5) или городу", catchall=True)
    async def query(self, ctx: FeatureContext, query: str):
        q = query.strip()
        if _OFFSET_RE.fullmatch(q):
            result = _time_by_offset(q)
            if result is None:
                await ctx.reply("Некорректное смещение (от -12 до +14)")
                return
            await ctx.reply(result, html=True, markdown=False)
            return
        result = _time_by_city(q)
        if result is None:
            await ctx.reply(f"Город «{q}» не найден")
            return
        await ctx.reply(result, html=True, markdown=False)

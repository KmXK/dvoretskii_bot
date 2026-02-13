import re
from datetime import timedelta


def parse_duration(raw: str) -> timedelta | None:
    if raw.isdigit():
        return timedelta(minutes=int(raw))

    duration_pattern = re.compile(r"(?P<value>\d+)\s*(?P<unit>[smhd])", re.IGNORECASE)
    total_seconds = 0

    for match in duration_pattern.finditer(raw):
        value = int(match.group("value"))
        unit = match.group("unit").lower()

        if unit == "s":
            total_seconds += value
        elif unit == "m":
            total_seconds += value * 60
        elif unit == "h":
            total_seconds += value * 3600
        elif unit == "d":
            total_seconds += value * 86400

    if total_seconds == 0:
        return None

    return timedelta(seconds=total_seconds)


def format_timedelta(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    parts: list[str] = []

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if seconds and not parts:
        parts.append(f"{seconds}с")

    return " ".join(parts) if parts else "несколько секунд"

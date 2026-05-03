import re
from datetime import datetime, time, timedelta


def parse_time_input(text: str) -> list[time]:
    times: list[time] = []
    text = text.strip()

    interval_pattern = r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2}),(\d+)"

    while True:
        match = re.search(interval_pattern, text)
        if not match:
            break

        start_hour = int(match.group(1))
        start_minute = int(match.group(2))
        end_hour = int(match.group(3))
        end_minute = int(match.group(4))
        step_minutes = int(match.group(5))

        if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
            raise ValueError(
                f"Неверное начальное время: {start_hour}:{start_minute:02d}"
            )
        if not (0 <= end_hour <= 23 and 0 <= end_minute <= 59):
            raise ValueError(f"Неверное конечное время: {end_hour}:{end_minute:02d}")
        if step_minutes <= 0:
            raise ValueError("Шаг должен быть положительным числом")

        start_time = time(hour=start_hour, minute=start_minute)
        end_time = time(hour=end_hour, minute=end_minute)

        current = datetime.combine(datetime.today(), start_time)
        end_dt = datetime.combine(datetime.today(), end_time)

        if current > end_dt:
            raise ValueError("Начальное время должно быть меньше или равно конечному")

        interval_times: list[time] = []
        while current <= end_dt:
            t = current.time()
            if t not in times and t not in interval_times:
                interval_times.append(t)
            current += timedelta(minutes=step_minutes)

        times.extend(interval_times)

        text = text[: match.start()] + text[match.end() :]

    parts = text.split()
    for part in parts:
        part = part.strip()
        if not part:
            continue

        time_parts = part.split(":")
        if len(time_parts) != 2:
            raise ValueError(f"Неверный формат времени: {part}")

        hour = int(time_parts[0])
        minute = int(time_parts[1])

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Неверное время: {hour}:{minute:02d}")

        t = time(hour=hour, minute=minute)
        if t not in times:
            times.append(t)

    return sorted(times)

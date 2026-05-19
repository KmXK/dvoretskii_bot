from dataclasses import dataclass, field


@dataclass
class HolidayCache:
    date: str  # YYYY-MM-DD
    holidays: list[str] = field(default_factory=list)

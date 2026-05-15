"""Парсер массового импорта истории тенниса.

Один payload = много дней. Каждый день — отдельный блок:

    ГГГГ-ММ-ДД @opp                       — день с партиями построчно ниже
    ГГГГ-ММ-ДД @opp 5:3                   — агрегатный день, одной строкой
    11:7                                   — партия (под детальным днём)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from steward.tennis.engine import is_valid_party_score


_DATE_LINE_RE = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2})"
    r"\s+(?P<opponent>\S+(?:\s+\S+)*?)"
    r"(?:\s+(?P<a>\d+)\s*[:\-/x]\s*(?P<b>\d+))?"
    r"\s*$",
    re.UNICODE,
)


@dataclass
class BulkEntry:
    line_no: int
    date: datetime
    opponent_raw: str
    mode: str  # "aggregate" | "detailed"
    wins_a: int | None = None
    wins_b: int | None = None
    score_pairs: list[tuple[int, int]] = field(default_factory=list)


def parse_score_pair(line: str) -> tuple[int, int]:
    nums = re.findall(r"\d+", line)
    if len(nums) != 2:
        raise ValueError(f"«{line}» — не похоже на счёт партии (нужны два числа)")
    return int(nums[0]), int(nums[1])


def parse_bulk_history(text: str) -> list[BulkEntry]:
    """Парсит мульти-дневной payload. Бросает ValueError при первой проблеме.

    Возвращает список BulkEntry (можно потом резолвить оппонентов и сохранять).
    """
    entries: list[BulkEntry] = []
    current: BulkEntry | None = None

    def _finalize() -> None:
        nonlocal current
        if current is None:
            return
        if current.mode == "detailed" and not current.score_pairs:
            raise ValueError(
                f"строка {current.line_no}: «detailed» день без партий — "
                f"добавь хотя бы одну строку «11:7» или впиши счёт сразу: «{current.date.date()} ... 5:3»"
            )
        entries.append(current)
        current = None

    for idx, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue

        m = _DATE_LINE_RE.match(line)
        if m:
            _finalize()
            date_str = m.group("date")
            opponent = m.group("opponent").strip()
            try:
                date = datetime.fromisoformat(date_str)
            except ValueError:
                raise ValueError(f"строка {idx}: не понимаю дату «{date_str}»")

            agg_a = m.group("a")
            agg_b = m.group("b")
            if agg_a is not None:
                a, b = int(agg_a), int(agg_b)
                if a < 0 or b < 0:
                    raise ValueError(f"строка {idx}: отрицательный счёт")
                if a == 0 and b == 0:
                    raise ValueError(f"строка {idx}: нужна хотя бы одна победа")
                current = BulkEntry(
                    line_no=idx,
                    date=date,
                    opponent_raw=opponent,
                    mode="aggregate",
                    wins_a=a,
                    wins_b=b,
                )
                _finalize()
            else:
                current = BulkEntry(
                    line_no=idx,
                    date=date,
                    opponent_raw=opponent,
                    mode="detailed",
                )
            continue

        if current is None:
            raise ValueError(
                f"строка {idx}: партия «{line}» без даты выше. "
                f"Каждый день начинается со строки «ГГГГ-ММ-ДД @оппонент»."
            )
        if current.mode == "aggregate":
            raise ValueError(
                f"строка {idx}: после агрегатного дня партии не нужны. "
                f"Если хочешь детально — убери счёт из строки с датой."
            )
        a, b = parse_score_pair(line)
        if not is_valid_party_score(a, b):
            raise ValueError(
                f"строка {idx}: «{line}» не похоже на партию (правило 11 + разница ≥2)"
            )
        current.score_pairs.append((a, b))

    _finalize()

    if not entries:
        raise ValueError("Пустой ввод — ничего не распознал")
    return entries

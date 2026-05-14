"""Фича настольного тенниса: live-сессии, импорт истории, статистика.

Архитектурно опирается на steward.tennis.room_manager — там же лежит
WebSocket-хендлер и фоновая корутина TTL. Сама фича — тонкий слой команд
бота, который умеет создавать/закрывать сессии и импортировать прошедшие.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from steward.data.models.tennis import TennisMatch, TennisSession
from steward.framework import (
    Button,
    Feature,
    FeatureContext,
    Keyboard,
    ask,
    choice,
    collection,
    confirm,
    on_init,
    resource_author,
    subcommand,
    wizard,
)
from steward.helpers.validation import Error, try_get, validate_message_text
from steward.helpers.webapp import _get_direct_url, get_webapp_deep_link
from steward.tennis.engine import (
    SIDE_A,
    SIDE_B,
    aggregate_session_matches,
    is_valid_party_score,
    player_stats,
    session_wins,
)
from steward.tennis.room_manager import get_manager


def _parse_aggregate_score(text: str) -> tuple[int, int]:
    parts = text.strip().replace("-", ":").replace(" ", ":").split(":")
    parts = [p for p in parts if p != ""]
    if len(parts) != 2:
        raise ValueError("Формат: «5:3»")
    a, b = int(parts[0]), int(parts[1])
    if a < 0 or b < 0:
        raise ValueError("Счёт не может быть отрицательным")
    if a == 0 and b == 0:
        raise ValueError("Нужна хотя бы одна победа")
    return a, b


def _parse_detailed_matches(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        sep = ":" if ":" in line else "-" if "-" in line else " "
        parts = [p for p in line.replace(sep, " ").split() if p != ""]
        if len(parts) != 2:
            raise ValueError(f"«{raw_line}» — не похоже на счёт партии")
        a, b = int(parts[0]), int(parts[1])
        if not is_valid_party_score(a, b):
            raise ValueError(f"«{raw_line}» — невалидный счёт партии")
        out.append((a, b))
    if not out:
        raise ValueError("Нужна хотя бы одна партия")
    return out


def _parse_date(text: str) -> datetime:
    text = text.strip()
    return datetime.fromisoformat(text)


_DATE_LINE_RE = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2})"          # ISO дата
    r"\s+(?P<opponent>\S+(?:\s+\S+)*?)"         # имя/юзернейм/id (не жадно)
    r"(?:\s+(?P<a>\d+)\s*[:\-/x]\s*(?P<b>\d+))?"  # опциональный агрегатный счёт
    r"\s*$",
    re.UNICODE,
)


@dataclass
class _BulkEntry:
    line_no: int
    date: datetime
    opponent_raw: str
    mode: str  # "aggregate" | "detailed"
    wins_a: int | None = None
    wins_b: int | None = None
    score_pairs: list[tuple[int, int]] = field(default_factory=list)


def _parse_score_pair(line: str) -> tuple[int, int]:
    nums = re.findall(r"\d+", line)
    if len(nums) != 2:
        raise ValueError(f"«{line}» — не похоже на счёт партии (нужны два числа)")
    return int(nums[0]), int(nums[1])


def _parse_bulk_history(text: str) -> list[_BulkEntry]:
    """Парсит мульти-дневной payload. Каждый блок — день.

    Формат:
      «<дата> <оппонент> <a:b>» — агрегатный день (одна строка)
      «<дата> <оппонент>» затем строки «<a>:<b>» — день с партиями построчно.

    Дата в ISO ГГГГ-ММ-ДД, оппонент — @username или числовой id. Пустые строки
    разрешены и игнорируются. Бросает ValueError при первой проблеме.
    """
    entries: list[_BulkEntry] = []
    current: _BulkEntry | None = None

    def _finalize():
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
                current = _BulkEntry(
                    line_no=idx,
                    date=date,
                    opponent_raw=opponent,
                    mode="aggregate",
                    wins_a=a,
                    wins_b=b,
                )
                _finalize()  # агрегатный — одной строкой
            else:
                current = _BulkEntry(
                    line_no=idx,
                    date=date,
                    opponent_raw=opponent,
                    mode="detailed",
                )
            continue

        # не дата — значит, счёт партии для текущего блока
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
        a, b = _parse_score_pair(line)
        if not is_valid_party_score(a, b):
            raise ValueError(
                f"строка {idx}: «{line}» не похоже на партию (правило 11 + разница ≥2)"
            )
        current.score_pairs.append((a, b))

    _finalize()

    if not entries:
        raise ValueError("Пустой ввод — ничего не распознал")
    return entries


def _format_user(users_collection, user_id: int) -> str:
    user = users_collection.find_by(id=user_id)
    if user is None:
        return f"id{user_id}"
    if getattr(user, "username", None):
        return f"@{user.username}"
    name = getattr(user, "name", None) or getattr(user, "first_name", None)
    return name or f"id{user_id}"


def _format_session_line(session: TennisSession, users) -> str:
    wins_a, wins_b = session_wins(session)
    date = session.started_at.strftime("%Y-%m-%d")
    name_a = _format_user(users, session.player_a_id)
    name_b = _format_user(users, session.player_b_id)
    tag = " · live" if session.ended_at is None else (
        " · timeout" if session.closed_reason == "timeout" else ""
    )
    parties = "агрегат" if session.is_aggregate_only else f"{len(session.matches)} парт."
    return f"#{session.id} {date} · {name_a} {wins_a}:{wins_b} {name_b} · {parties}{tag}"


def _build_webapp_keyboard(bot, chat_id: int, is_private: bool) -> Keyboard | None:
    direct_url = _get_direct_url()
    if direct_url and is_private:
        return Keyboard.row(Button("🏓 Открыть табло", webapp=direct_url))
    link = get_webapp_deep_link(bot, chat_id)
    if not link:
        return None
    return Keyboard.row(Button("🏓 Открыть табло", url=link))


class TennisFeature(Feature):
    command = "tennis"
    description = "Настольный теннис: live-табло, импорт истории, статистика"
    help_examples = [
        "/tennis — список последних сессий",
        "/tennis start — открыть live-табло с оппонентом",
        "/tennis start @ivan — запустить против конкретного игрока",
        "/tennis serve — переключить первую подачу",
        "/tennis set 5 — сет = 5 партий (0 = выключить)",
        "/tennis close — закрыть мою активную сессию",
        "/tennis add — записать прошедший день (агрегат или построчно)",
        "/tennis stats — моя статистика",
        "/tennis stats @ivan — статистика игрока",
        "/tennis history — пагинатор по сессиям чата",
    ]

    sessions = collection("tennis_sessions")
    users = collection("users")

    # ── on_init: фон ─────────────────────────────────────────────────────────

    @on_init
    async def _wire_room_manager(self):
        manager = get_manager()
        manager.configure_notifications(
            self.bot,
            user_display=lambda uid: _format_user(self.users, uid),
        )
        manager.start_ttl_watcher(self.repository)

    # ── helpers ──────────────────────────────────────────────────────────────

    def resolve_owner(self, field: str, value: Any) -> int | None:
        if field == "session_id":
            session = self.sessions.find_by(id=int(value))
            return session.initiator_id if session else None
        return None

    def _resolve_user(self, identifier: str):
        identifier = identifier.lstrip("@").strip()
        if not identifier:
            return None
        try:
            return self.users.find_by(id=int(identifier))
        except ValueError:
            pass
        target = identifier.lower()
        return self.users.find_one(
            lambda u: u.username and u.username.lower() == target
        )

    def _active_session_for(self, user_id: int, chat_id: int | None = None) -> TennisSession | None:
        for s in self.sessions:
            if s.ended_at is not None:
                continue
            if chat_id is not None and s.chat_id != chat_id:
                continue
            if user_id in (s.player_a_id, s.player_b_id, s.initiator_id):
                return s
        return None

    async def _open_session(
        self,
        ctx: FeatureContext,
        opponent_id: int,
        *,
        first_server: str = SIDE_A,
        set_size: int = 0,
    ) -> TennisSession | None:
        existing = self._active_session_for(ctx.user_id, ctx.chat_id)
        if existing is not None:
            await ctx.reply(
                f"У тебя уже есть открытая сессия #{existing.id}. "
                f"Сначала закрой её через /tennis close."
            )
            return None

        now = datetime.now()
        session = self.sessions.add(TennisSession(
            id=0,
            chat_id=ctx.chat_id,
            player_a_id=ctx.user_id,
            player_b_id=opponent_id,
            started_at=now,
            last_activity_at=now,
            initiator_id=ctx.user_id,
            first_server=first_server,
            set_size=set_size,
        ))
        await self.sessions.save()

        is_private = ctx.message is not None and ctx.message.chat.type == "private"
        kb = _build_webapp_keyboard(self.bot, ctx.chat_id, is_private)
        name_a = _format_user(self.users, ctx.user_id)
        name_b = _format_user(self.users, opponent_id)
        await ctx.reply(
            f"🏓 Сессия #{session.id}: {name_a} vs {name_b}\n"
            f"Жми кнопку, чтобы открыть табло.",
            keyboard=kb,
        )
        return session

    # ── subcommands ──────────────────────────────────────────────────────────

    @subcommand("", description="Список последних сессий")
    async def list_(self, ctx: FeatureContext):
        chat_sessions = self.sessions.filter(chat_id=ctx.chat_id)
        chat_sessions.sort(key=lambda s: s.started_at, reverse=True)
        if not chat_sessions:
            await ctx.reply(
                "Сессий пока нет.\n"
                "Запусти live: /tennis start или импортируй прошедшую: /tennis add."
            )
            return
        lines = [_format_session_line(s, self.users) for s in chat_sessions[:10]]
        await ctx.reply("Последние сессии:\n" + "\n".join(lines))

    @subcommand("start", description="Запустить live-сессию (визард)")
    async def start_wizard_cmd(self, ctx: FeatureContext):
        await self.start_wizard("tennis:start", ctx)

    @subcommand("start <opponent:rest>", description="Запустить сессию против указанного игрока")
    async def start_with_opponent(self, ctx: FeatureContext, opponent: str):
        user = self._resolve_user(opponent)
        if user is None:
            await ctx.reply(f"Не нашёл игрока «{opponent}». Используй @username или id.")
            return
        if user.id == ctx.user_id:
            await ctx.reply("Сам с собой играть не интересно.")
            return
        await self._open_session(ctx, user.id)

    @subcommand("serve", description="Переключить первую подачу в активной сессии")
    async def serve_toggle(self, ctx: FeatureContext):
        session = self._active_session_for(ctx.user_id, ctx.chat_id)
        if session is None:
            await ctx.reply("Нет активной сессии в этом чате.")
            return
        session.first_server = SIDE_B if session.first_server == SIDE_A else SIDE_A
        await self.sessions.save()
        room = get_manager().attach(session, self.repository)
        await room.broadcast()
        server_player_id = (
            session.player_a_id if session.first_server == SIDE_A else session.player_b_id
        )
        await ctx.reply(
            f"🏓 Первую подачу пометил за {_format_user(self.users, server_player_id)}."
        )

    @subcommand("set <size:int>", description="Размер сета (0 = без сетов)")
    async def set_size_cmd(self, ctx: FeatureContext, size: int):
        session = self._active_session_for(ctx.user_id, ctx.chat_id)
        if session is None:
            await ctx.reply("Нет активной сессии в этом чате.")
            return
        size = max(0, int(size))
        session.set_size = size
        # пересчитаем сколько сетов уже завершено
        if size > 0:
            completed = len(session.matches) // size
            session.sets_announced = min(session.sets_announced, completed)
        else:
            session.sets_announced = 0
        await self.sessions.save()
        room = get_manager().attach(session, self.repository)
        await room.broadcast()
        if size == 0:
            await ctx.reply("Сеты отключены.")
        else:
            await ctx.reply(f"Сет = {size} парт.")

    @subcommand("close", description="Закрыть твою активную сессию")
    async def close_(self, ctx: FeatureContext):
        session = self._active_session_for(ctx.user_id, ctx.chat_id)
        if session is None:
            await ctx.reply("У тебя нет активных сессий в этом чате.")
            return
        room = get_manager().attach(session, self.repository)
        await room.close("manual")
        await room.broadcast("closed", reason="manual")
        wins_a, wins_b = session_wins(session)
        name_a = _format_user(self.users, session.player_a_id)
        name_b = _format_user(self.users, session.player_b_id)
        await ctx.reply(
            f"🏓 Сессия #{session.id} закрыта.\n"
            f"Итог: {name_a} {wins_a} : {wins_b} {name_b}"
        )

    @subcommand("add", description="Записать прошедшую сессию (импорт истории)")
    async def add_(self, ctx: FeatureContext):
        await self.start_wizard("tennis:add", ctx)

    @subcommand("bulk", description="Массовый импорт истории одним сообщением")
    async def bulk(self, ctx: FeatureContext):
        await self.start_wizard("tennis:bulk", ctx)

    @subcommand("stats", description="Твоя статистика")
    async def stats_self(self, ctx: FeatureContext):
        await self._render_stats(ctx, ctx.user_id)

    @subcommand("stats <opponent:rest>", description="Статистика игрока")
    async def stats_other(self, ctx: FeatureContext, opponent: str):
        user = self._resolve_user(opponent)
        if user is None:
            await ctx.reply(f"Не нашёл игрока «{opponent}».")
            return
        await self._render_stats(ctx, user.id)

    @subcommand("history", description="История сессий чата (пагинированно)")
    async def history(self, ctx: FeatureContext):
        chat_sessions = self.sessions.filter(chat_id=ctx.chat_id)
        chat_sessions.sort(key=lambda s: s.started_at, reverse=True)
        if not chat_sessions:
            await ctx.reply("История пуста.")
            return
        lines = [_format_session_line(s, self.users) for s in chat_sessions]
        await ctx.reply("📜 История сессий:\n" + "\n".join(lines))

    async def _render_stats(self, ctx: FeatureContext, user_id: int) -> None:
        stats = player_stats(list(self.sessions), user_id)
        name = _format_user(self.users, user_id)
        if stats.matches == 0:
            await ctx.reply(f"У {name} пока нет партий.")
            return

        def _fmt_dur(s: float | None) -> str:
            if s is None:
                return "—"
            if s < 60:
                return f"{int(s)}с"
            if s < 3600:
                return f"{int(s // 60)} мин"
            return f"{s / 3600:.1f} ч"

        lines = [
            f"📊 Статистика игрока {name}:",
            f"Сессий: {stats.sessions}",
            f"Партий: {stats.matches} (W{stats.wins} / L{stats.losses})",
            f"Win-rate: {stats.win_rate * 100:.0f}%",
            f"Серия побед (max): {stats.longest_win_streak}",
        ]
        if stats.median_matches_per_session is not None:
            lines.append(f"Партий за сессию (медиана): {stats.median_matches_per_session:g}")
        if stats.median_point_diff is not None:
            lines.append(f"Разница очков (медиана): {stats.median_point_diff:g}")
        if stats.median_match_duration_s is not None:
            lines.append(f"Длина партии (медиана): {_fmt_dur(stats.median_match_duration_s)}")
        if stats.median_gap_s is not None:
            lines.append(f"Пауза между партиями (медиана): {_fmt_dur(stats.median_gap_s)}")
        await ctx.reply("\n".join(lines))

    # ── wizard: start ────────────────────────────────────────────────────────

    @wizard(
        "tennis:start",
        ask(
            "opponent_raw",
            "С кем играешь? Пришли @username или id оппонента.",
            validator=validate_message_text([try_get(lambda t: t.strip(), "Пустой ввод")]),
        ),
        choice(
            "first_server",
            "Кто подаёт первым?",
            [
                ("Я", SIDE_A),
                ("Оппонент", SIDE_B),
            ],
        ),
        ask(
            "set_size",
            "Размер сета (партий в одном сете). 0 — без сетов.",
            validator=validate_message_text([
                try_get(lambda t: max(0, int(t.strip())), "Введи число от 0"),
            ]),
        ),
        confirm(
            "confirmed",
            lambda state: (
                f"Запустить сессию против {state.get('opponent_raw', '?')}? "
                f"Подаёт {'ты' if state.get('first_server') == SIDE_A else 'оппонент'}"
                f"{', сетов нет' if not state.get('set_size') else f', сет = {state.get('set_size')} парт.'}."
            ),
        ),
    )
    async def _on_start_done(
        self,
        ctx: FeatureContext,
        opponent_raw: str,
        first_server: str,
        set_size: int,
        confirmed: bool,
        **_,
    ):
        if not confirmed:
            await ctx.reply("Окей, не запускаем.")
            return
        user = self._resolve_user(opponent_raw)
        if user is None:
            await ctx.reply(f"Не нашёл игрока «{opponent_raw}». Попробуй /tennis start ещё раз.")
            return
        if user.id == ctx.user_id:
            await ctx.reply("Сам с собой играть не интересно.")
            return
        await self._open_session(
            ctx,
            user.id,
            first_server=first_server,
            set_size=int(set_size or 0),
        )

    # ── wizard: add (история) ────────────────────────────────────────────────

    @wizard(
        "tennis:add",
        ask(
            "opponent_raw",
            "С кем играли? @username или id.",
            validator=validate_message_text([try_get(lambda t: t.strip(), "Пустой ввод")]),
        ),
        ask(
            "date",
            "Когда играли? Дата в формате ГГГГ-ММ-ДД (например, 2024-05-14).",
            validator=validate_message_text([try_get(_parse_date, "Не понимаю дату. Формат: ГГГГ-ММ-ДД")]),
        ),
        choice(
            "mode",
            "Что записываем?",
            [
                ("Только итог за день (5:3)", "aggregate"),
                ("Каждую партию построчно (11:7)", "detailed"),
            ],
        ),
        ask(
            "agg_score",
            "Введи итог как «твои:оппонента», например 5:3.",
            validator=validate_message_text([try_get(_parse_aggregate_score, "Не понял. Формат: 5:3")]),
            when=lambda s: s.get("mode") == "aggregate",
        ),
        ask(
            "detailed_matches",
            "Введи партии построчно, каждая в формате «11:7». Минимум одна.",
            validator=validate_message_text([
                try_get(_parse_detailed_matches, "Не понял. Каждую партию пиши с новой строки как 11:7"),
            ]),
            when=lambda s: s.get("mode") == "detailed",
        ),
    )
    async def _on_add_done(self, ctx: FeatureContext, **state):
        opponent_raw = state.get("opponent_raw", "")
        user = self._resolve_user(opponent_raw)
        if user is None:
            await ctx.reply(f"Не нашёл игрока «{opponent_raw}». Импорт отменён.")
            return
        if user.id == ctx.user_id:
            await ctx.reply("Сам с собой играть не интересно.")
            return

        date: datetime = state["date"]
        mode = state.get("mode")

        if mode == "aggregate":
            wins_a, wins_b = state["agg_score"]
            matches = aggregate_session_matches(date, wins_a, wins_b)
            is_aggregate = True
            ended_at = date
        else:
            score_pairs: list[tuple[int, int]] = state["detailed_matches"]
            cur = date
            matches: list[TennisMatch] = []
            for sa, sb in score_pairs:
                ended = cur
                winner = SIDE_A if sa > sb else SIDE_B
                matches.append(TennisMatch(
                    started_at=cur,
                    ended_at=ended,
                    winner=winner,
                    score_a=sa,
                    score_b=sb,
                ))
                cur = ended
            is_aggregate = False
            ended_at = cur

        session = self.sessions.add(TennisSession(
            id=0,
            chat_id=ctx.chat_id,
            player_a_id=ctx.user_id,
            player_b_id=user.id,
            started_at=date,
            ended_at=ended_at,
            last_activity_at=date,
            matches=matches,
            is_aggregate_only=is_aggregate,
            closed_reason="manual",
            initiator_id=ctx.user_id,
        ))
        await self.sessions.save()

        wins_a, wins_b = session_wins(session)
        name_a = _format_user(self.users, ctx.user_id)
        name_b = _format_user(self.users, user.id)
        await ctx.reply(
            f"✅ Записано: сессия #{session.id} от {date.strftime('%Y-%m-%d')}.\n"
            f"{name_a} {wins_a} : {wins_b} {name_b} · "
            f"{'агрегат' if is_aggregate else f'{len(matches)} парт.'}"
        )

    # ── wizard: bulk (массовый импорт) ───────────────────────────────────────

    _BULK_HELP = (
        "Пришли историю одним сообщением. Формат построчный:\n"
        "\n"
        "  ГГГГ-ММ-ДД @оппонент          — день с партиями построчно ниже\n"
        "  ГГГГ-ММ-ДД @оппонент 5:3      — агрегатный день, одной строкой\n"
        "\n"
        "Пример (можешь сразу скопировать):\n"
        "\n"
        "  2024-05-10 @ivan 5:3\n"
        "  2024-05-12 @ivan 7:2\n"
        "  2024-05-15 @ivan\n"
        "  11:7\n"
        "  11:9\n"
        "  9:11\n"
        "  12:10\n"
        "  2024-05-20 @ivan 4:6\n"
        "  2024-05-22 @ivan\n"
        "  11:5\n"
        "  9:11\n"
        "  11:8\n"
        "  2024-05-25 @ivan 3:4\n"
        "\n"
        "Пустые строки игнорятся. Оппонент задаётся отдельно для каждого дня — "
        "удобно если играл с разными людьми."
    )

    @wizard(
        "tennis:bulk",
        ask(
            "payload",
            lambda _: TennisFeature._BULK_HELP,
            validator=validate_message_text([try_get(lambda t: t, "Пустой ввод")]),
        ),
    )
    async def _on_bulk_done(self, ctx: FeatureContext, payload: str, **_):
        try:
            entries = _parse_bulk_history(payload)
        except ValueError as e:
            await ctx.reply(
                f"❌ Не получилось распарсить:\n{e}\n\n"
                f"Пришли /tennis bulk ещё раз с исправленным текстом."
            )
            return

        # 1) Резолвим всех оппонентов заранее — чтобы не создавать половину
        resolved: list[tuple[_BulkEntry, int]] = []
        for entry in entries:
            user = self._resolve_user(entry.opponent_raw)
            if user is None:
                await ctx.reply(
                    f"❌ Строка {entry.line_no}: не нашёл оппонента «{entry.opponent_raw}». "
                    f"Используй @username или числовой id. Импорт отменён."
                )
                return
            if user.id == ctx.user_id:
                await ctx.reply(
                    f"❌ Строка {entry.line_no}: сам с собой играть не получится. Импорт отменён."
                )
                return
            resolved.append((entry, user.id))

        # 2) Все валидные — создаём сессии и сохраняем одной транзакцией
        created_lines: list[str] = []
        for entry, opp_id in resolved:
            session = self._build_session_from_entry(entry, opp_id, ctx)
            self.sessions.add(session)
            wins_a, wins_b = session_wins(session)
            tag = "агрегат" if session.is_aggregate_only else f"{len(session.matches)} парт."
            created_lines.append(
                f"#{session.id} {entry.date.strftime('%Y-%m-%d')} · "
                f"{wins_a}:{wins_b} · {tag}"
            )
        await self.sessions.save()

        await ctx.reply(
            f"✅ Импортировано {len(resolved)} сессий:\n" + "\n".join(created_lines)
        )

    def _build_session_from_entry(
        self,
        entry: _BulkEntry,
        opponent_id: int,
        ctx: FeatureContext,
    ) -> TennisSession:
        if entry.mode == "aggregate":
            matches = aggregate_session_matches(entry.date, entry.wins_a or 0, entry.wins_b or 0)
            return TennisSession(
                id=0,
                chat_id=ctx.chat_id,
                player_a_id=ctx.user_id,
                player_b_id=opponent_id,
                started_at=entry.date,
                ended_at=entry.date,
                last_activity_at=entry.date,
                matches=matches,
                is_aggregate_only=True,
                closed_reason="manual",
                initiator_id=ctx.user_id,
            )
        # detailed
        cur = entry.date
        matches: list[TennisMatch] = []
        for sa, sb in entry.score_pairs:
            ended = cur
            winner = SIDE_A if sa > sb else SIDE_B
            matches.append(TennisMatch(
                started_at=cur,
                ended_at=ended,
                winner=winner,
                score_a=sa,
                score_b=sb,
            ))
            cur = ended
        return TennisSession(
            id=0,
            chat_id=ctx.chat_id,
            player_a_id=ctx.user_id,
            player_b_id=opponent_id,
            started_at=entry.date,
            ended_at=cur,
            last_activity_at=entry.date,
            matches=matches,
            is_aggregate_only=False,
            closed_reason="manual",
            initiator_id=ctx.user_id,
        )

from dataclasses import dataclass
from datetime import datetime, timezone

from steward.data.models.curse import CurseParticipant
from steward.data.repository import Repository


@dataclass
class PunishmentTodayEntry:
    user_id: int
    name: str
    curse_count: int


def _display_name(username: str | None, user_id: int) -> str:
    return f"@{username}" if username else f"@{user_id}"


def _user_name(repo: Repository, user_id: int) -> str:
    user = next((u for u in repo.db.users if u.id == user_id), None)
    if user is None:
        return _display_name(None, user_id)
    return _display_name(user.username, user_id)


def _participant_since(participant: CurseParticipant) -> datetime:
    return participant.last_done_at or participant.subscribed_at


async def get_current_curse_count(queryable, user_id: int, since: datetime | None) -> int:
    if since is None:
        promql = f'sum(bot_curse_words_total{{user_id="{user_id}"}})'
    else:
        now = datetime.now(timezone.utc)
        seconds = max(int((now - since).total_seconds()), 1)
        promql = f'sum(increase(bot_curse_words_total{{user_id="{user_id}"}}[{seconds}s]))'

    results = await queryable.query(promql)
    if not results:
        return 0
    return max(int(round(results[0].value)), 0)


async def build_punishment_today_entries(
    repo: Repository, queryable, chat_id: int,
) -> list[PunishmentTodayEntry]:
    user_ids_in_chat = {
        user.id
        for user in repo.db.users
        if chat_id in user.chat_ids
    }

    entries: list[PunishmentTodayEntry] = []
    for participant in repo.db.curse_participants:
        if participant.user_id not in user_ids_in_chat:
            continue

        count = await get_current_curse_count(
            queryable,
            participant.user_id,
            _participant_since(participant),
        )
        if count <= 0:
            continue

        entries.append(
            PunishmentTodayEntry(
                user_id=participant.user_id,
                name=_user_name(repo, participant.user_id),
                curse_count=count,
            )
        )

    entries.sort(key=lambda entry: (-entry.curse_count, entry.name.lower()))
    return entries


def format_punishment_today_text(repo: Repository, entries: list[PunishmentTodayEntry]) -> str:
    if not repo.db.curse_punishments:
        return "Наказания не настроены."
    if not entries:
        return "Сегодня наказаний нет."

    lines = ["Наказания на сегодня:", ""]
    punishments = sorted(repo.db.curse_punishments, key=lambda item: item.id)
    for index, entry in enumerate(entries):
        lines.append(f"`{entry.name}` — {entry.curse_count} плохих слов")
        for punishment in punishments:
            lines.append(f"{punishment.coeff * entry.curse_count} {punishment.title}")
        if index != len(entries) - 1:
            lines.append("")
    return "\n".join(lines)

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from steward.bot.context import ChatBotContext
from steward.data.models.curse import CurseParticipant, CursePunishment
from steward.delayed_action.curse_punishment_digest import CursePunishmentDigestDelayedAction
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.handlers.handler import Handler
from steward.helpers.command_validation import ValidationArgumentsError, validate_command_msg
from steward.helpers.curse_punishment import (
    build_punishment_today_entries,
    format_punishment_today_text,
    get_current_curse_count,
)

MSK = ZoneInfo("Europe/Minsk")


def _parse_words(raw: str) -> list[str]:
    words = []
    seen = set()
    for word in raw.split():
        normalized = word.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            words.append(normalized)
    return words
class CurseHandler(Handler):
    async def init(self):
        has_digest_action = any(
            isinstance(action, CursePunishmentDigestDelayedAction)
            for action in self.repository.db.delayed_actions
        )
        if has_digest_action:
            return

        self.repository.db.delayed_actions.append(
            CursePunishmentDigestDelayedAction(
                generator=ConstantGenerator(
                    start=datetime(2025, 1, 1, 22, 22, tzinfo=MSK),
                    period=timedelta(days=1),
                )
            )
        )
        await self.repository.save()

    async def chat(self, context: ChatBotContext):
        validation = validate_command_msg(
            context.update,
            "curse",
            r"(?P<args>.*)?",
        )
        if not validation:
            return False

        args = ((validation.args or {}).get("args") or "").strip()
        if args == "":
            raise ValidationArgumentsError()

        if args.isdigit():
            return await self._increment_metric(context, int(args))

        if args == "word_list":
            return await self._show_word_list(context)
        if args.startswith("word_list add "):
            return await self._add_words(context, args.removeprefix("word_list add ").strip())
        if args.startswith("word_list remove "):
            return await self._remove_words(context, args.removeprefix("word_list remove ").strip())

        if args == "punishment":
            return await self._show_punishments(context)
        if args == "punishment today":
            return await self._show_today(context)
        if args == "punishment subscribe":
            return await self._subscribe(context)
        if args == "punishment unsubscribe":
            return await self._unsubscribe(context)
        if args.startswith("punishment add "):
            rest = args.removeprefix("punishment add ").strip()
            return await self._add_punishment(context, rest)
        if args.startswith("punishment remove "):
            value = args.removeprefix("punishment remove ").strip()
            return await self._remove_punishment(context, value)

        if args == "done":
            return await self._done(context, None)
        if args.startswith("done "):
            value = args.removeprefix("done ").strip()
            if not value.isdigit():
                raise ValidationArgumentsError()
            return await self._done(context, int(value))

        raise ValidationArgumentsError()

    async def _increment_metric(self, context: ChatBotContext, count: int):
        if count <= 0:
            raise ValidationArgumentsError()

        context.metrics.inc("bot_curse_words_total", value=count)
        await context.message.reply_markdown(f"Добавил {count} плохих слов.")
        return True

    async def _show_word_list(self, context: ChatBotContext):
        words = sorted(self.repository.db.curse_words)
        if not words:
            await context.message.reply_markdown("Список матерных слов пуст.")
            return True

        await context.message.reply_markdown("Матерные слова:\n\n" + "\n".join(words))
        return True

    def _ensure_admin(self, context: ChatBotContext):
        user_id = context.message.from_user.id
        if not self.repository.is_admin(user_id):
            return False
        return True

    async def _add_words(self, context: ChatBotContext, raw_words: str):
        if not self._ensure_admin(context):
            await context.message.reply_markdown("Недостаточно прав.")
            return True

        items = _parse_words(raw_words)
        if not items:
            raise ValidationArgumentsError()

        added = []
        for word in items:
            if word not in self.repository.db.curse_words:
                self.repository.db.curse_words.add(word)
                added.append(word)

        if not added:
            await context.message.reply_markdown("Все слова уже есть в списке.")
            return True

        await self.repository.save()
        await context.message.reply_markdown("Добавлены слова: " + ", ".join(added))
        return True

    async def _remove_words(self, context: ChatBotContext, raw_words: str):
        if not self._ensure_admin(context):
            await context.message.reply_markdown("Недостаточно прав.")
            return True

        items = _parse_words(raw_words)
        if not items:
            raise ValidationArgumentsError()

        removed = []
        for word in items:
            if word in self.repository.db.curse_words:
                self.repository.db.curse_words.remove(word)
                removed.append(word)

        if not removed:
            await context.message.reply_markdown("Ни одно слово не найдено в списке.")
            return True

        await self.repository.save()
        await context.message.reply_markdown("Удалены слова: " + ", ".join(removed))
        return True

    async def _show_punishments(self, context: ChatBotContext):
        punishments = sorted(self.repository.db.curse_punishments, key=lambda item: item.id)
        if not punishments:
            await context.message.reply_markdown("Наказаний нет.")
            return True

        lines = ["Наказания:"]
        for punishment in punishments:
            lines.append(f"{punishment.id}. {punishment.coeff} -> {punishment.title}")
        await context.message.reply_markdown("\n".join(lines))
        return True

    async def _add_punishment(self, context: ChatBotContext, rest: str):
        if not self._ensure_admin(context):
            await context.message.reply_markdown("Недостаточно прав.")
            return True

        parts = rest.split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            raise ValidationArgumentsError()

        coeff = int(parts[0])
        title = parts[1].strip()
        if coeff <= 0 or title == "":
            raise ValidationArgumentsError()

        next_id = max((item.id for item in self.repository.db.curse_punishments), default=0) + 1
        punishment = CursePunishment(id=next_id, coeff=coeff, title=title)
        self.repository.db.curse_punishments.append(punishment)
        await self.repository.save()
        await context.message.reply_markdown(
            f"Наказание добавлено: {punishment.id}. {punishment.coeff} -> {punishment.title}",
        )
        return True

    async def _remove_punishment(self, context: ChatBotContext, raw_id: str):
        if not self._ensure_admin(context):
            await context.message.reply_markdown("Недостаточно прав.")
            return True

        if not raw_id.isdigit():
            raise ValidationArgumentsError()

        punishment_id = int(raw_id)
        punishment = next(
            (item for item in self.repository.db.curse_punishments if item.id == punishment_id),
            None,
        )
        if punishment is None:
            await context.message.reply_markdown("Наказание не найдено.")
            return True

        self.repository.db.curse_punishments.remove(punishment)
        await self.repository.save()
        await context.message.reply_markdown(f"Наказание {punishment_id} удалено.")
        return True

    def _find_participant(self, user_id: int) -> CurseParticipant | None:
        return next(
            (item for item in self.repository.db.curse_participants if item.user_id == user_id),
            None,
        )

    async def _subscribe(self, context: ChatBotContext):
        user_id = context.message.from_user.id
        chat_id = context.message.chat_id
        participant = self._find_participant(user_id)
        now = datetime.now(timezone.utc)

        if participant is None:
            participant = CurseParticipant(
                user_id=user_id,
                subscribed_at=now,
                last_done_at=now,
                source_chat_ids=[chat_id],
            )
            self.repository.db.curse_participants.append(participant)
            await self.repository.save()
            await context.message.reply_markdown("Подписка на наказания включена.")
            return True

        changed = False
        if chat_id not in participant.source_chat_ids:
            participant.source_chat_ids.append(chat_id)
            changed = True

        if changed:
            await self.repository.save()

        await context.message.reply_markdown("Подписка на наказания уже включена.")
        return True

    async def _unsubscribe(self, context: ChatBotContext):
        user_id = context.message.from_user.id
        participant = self._find_participant(user_id)
        if participant is None:
            await context.message.reply_markdown("Подписка на наказания не найдена.")
            return True

        self.repository.db.curse_participants.remove(participant)
        await self.repository.save()
        await context.message.reply_markdown("Подписка на наказания отключена.")
        return True

    async def _show_today(self, context: ChatBotContext):
        entries = await build_punishment_today_entries(
            self.repository,
            context.metrics,
            context.message.chat_id,
        )
        await context.message.reply_markdown(format_punishment_today_text(self.repository, entries))
        return True

    async def _done(self, context: ChatBotContext, punishment_id: int | None):
        user_id = context.message.from_user.id
        participant = self._find_participant(user_id)
        if participant is None:
            await context.message.reply_markdown("Сначала подпишись на наказания.")
            return True

        now = datetime.now(timezone.utc)
        if punishment_id is None:
            participant.last_done_at = now
            await self.repository.save()
            await context.message.reply_markdown("Отсчёт наказаний сброшен.")
            return True

        punishment = next(
            (item for item in self.repository.db.curse_punishments if item.id == punishment_id),
            None,
        )
        if punishment is None:
            await context.message.reply_markdown("Наказание не найдено.")
            return True

        current_count = await get_current_curse_count(
            context.metrics,
            user_id,
            participant.last_done_at or participant.subscribed_at,
        )
        total = punishment.coeff * current_count

        context.metrics.inc(
            "bot_curse_punishment_done_total",
            {
                "punishment_id": str(punishment.id),
                "punishment_title": punishment.title,
            },
            total,
        )
        participant.last_done_at = now
        await self.repository.save()
        await context.message.reply_markdown(
            f"Наказание засчитано: {total} {punishment.title}.",
        )
        return True

    def help(self):
        return (
            "/curse <n> | word_list [add <слова>|remove <слова>] | "
            "punishment [add <coeff> <название>|remove <id>|today|subscribe|unsubscribe] | "
            "done [id]"
        )

    def prompt(self):
        return (
            "▶ /curse — мат и наказания\n"
            "  Добавить вручную: /curse <n>\n"
            "  Список слов: /curse word_list\n"
            "  Добавить слова: /curse word_list add <слова через пробел>\n"
            "  Удалить слова: /curse word_list remove <слова через пробел>\n"
            "  Список наказаний: /curse punishment\n"
            "  Добавить наказание: /curse punishment add <coeff> <название>\n"
            "  Удалить наказание: /curse punishment remove <id>\n"
            "  Наказания сегодня: /curse punishment today\n"
            "  Подписаться: /curse punishment subscribe\n"
            "  Отписаться: /curse punishment unsubscribe\n"
            "  Завершить: /curse done [id]"
        )

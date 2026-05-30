from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from steward.data.models.curse import CurseParticipant, CursePunishment
from steward.delayed_action.curse_punishment_digest import (
    CursePunishmentDigestDelayedAction,
)
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.framework import (
    Feature,
    FeatureContext,
    collection,
    on_init,
    subcommand,
)
from steward.helpers.command_validation import ValidationArgumentsError
from steward.helpers.curse_punishment import (
    build_punishment_today_entries,
    format_punishment_today_text,
    get_current_curse_count,
)


_MSK = ZoneInfo("Europe/Minsk")


def _parse_words(raw: str) -> list[str]:
    out, seen = [], set()
    for word in raw.split():
        norm = word.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


class CurseFeature(Feature):
    command = "curse"
    description = "Маты и наказания"

    curse_words = collection("curse_words")
    curse_ignore_words = collection("curse_ignore_words")
    curse_punishments = collection("curse_punishments")
    curse_participants = collection("curse_participants")
    delayed_actions = collection("delayed_actions")

    @on_init
    async def _setup_digest(self):
        has_digest = any(
            isinstance(a, CursePunishmentDigestDelayedAction)
            for a in self.delayed_actions
        )
        if has_digest:
            return
        self.delayed_actions.add(
            CursePunishmentDigestDelayedAction(
                generator=ConstantGenerator(
                    start=datetime(2025, 1, 1, 22, 22, tzinfo=_MSK),
                    period=timedelta(days=1),
                )
            )
        )
        await self.delayed_actions.save()

    @subcommand("<n:int>", description="Добавить N матов")
    async def increment(self, ctx: FeatureContext, n: int):
        if n <= 0:
            raise ValidationArgumentsError()
        ctx.metrics.inc("bot_curse_words_total", value=n)
        await ctx.reply(f"Добавил {n} плохих слов.")

    @subcommand("word_list", description="Список матерных слов")
    async def show_word_list(self, ctx: FeatureContext):
        words = sorted(self.curse_words.all())
        if not words:
            await ctx.reply("Список матерных слов пуст.")
            return
        await ctx.reply("Матерные слова:\n\n" + "\n".join(words))

    @subcommand("word_list add <words:rest>", description="Добавить слова", admin=True)
    async def add_words(self, ctx: FeatureContext, words: str):
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()
        added = self.curse_words.add_many(items)
        if not added:
            await ctx.reply("Все слова уже есть в списке.")
            return
        await self.curse_words.save()
        await ctx.reply("Добавлены слова: " + ", ".join(added))

    @subcommand("word_list remove <words:rest>", description="Удалить слова", admin=True)
    async def remove_words(self, ctx: FeatureContext, words: str):
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()
        removed = self.curse_words.remove_many(items)
        if not removed:
            await ctx.reply("Ни одно слово не найдено в списке.")
            return
        await self.curse_words.save()
        await ctx.reply("Удалены слова: " + ", ".join(removed))

    @subcommand("ignore_list", description="Список исключений для матерных слов")
    async def show_ignore_list(self, ctx: FeatureContext):
        words = sorted(self.curse_ignore_words.all())
        if not words:
            await ctx.reply("Список исключений пуст.")
            return
        await ctx.reply("Исключения:\n\n" + "\n".join(words))

    @subcommand("ignore_list add <words:rest>", description="Добавить исключения", admin=True)
    async def add_ignore_words(self, ctx: FeatureContext, words: str):
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()
        added = self.curse_ignore_words.add_many(items)
        if not added:
            await ctx.reply("Все исключения уже есть в списке.")
            return
        await self.curse_ignore_words.save()
        await ctx.reply("Добавлены исключения: " + ", ".join(added))

    @subcommand("ignore_list remove <words:rest>", description="Удалить исключения", admin=True)
    async def remove_ignore_words(self, ctx: FeatureContext, words: str):
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()
        removed = self.curse_ignore_words.remove_many(items)
        if not removed:
            await ctx.reply("Ни одно исключение не найдено в списке.")
            return
        await self.curse_ignore_words.save()
        await ctx.reply("Удалены исключения: " + ", ".join(removed))

    @subcommand("punishment", description="Список наказаний")
    async def show_punishments(self, ctx: FeatureContext):
        items = sorted(self.curse_punishments.all(), key=lambda p: p.id)
        if not items:
            await ctx.reply("Наказаний нет.")
            return
        lines = ["Наказания:"]
        for p in items:
            lines.append(f"{p.id}. {p.coeff} -> {p.title}")
        await ctx.reply("\n".join(lines))

    @subcommand("punishment today", description="Наказания сегодня")
    async def punishment_today(self, ctx: FeatureContext):
        entries = await build_punishment_today_entries(
            self.repository, ctx.metrics, ctx.chat_id,
        )
        await ctx.reply(format_punishment_today_text(self.repository, entries))

    @subcommand("punishment subscribe", description="Подписаться")
    async def subscribe(self, ctx: FeatureContext):
        user_id = ctx.user_id
        chat_id = ctx.chat_id
        participant = self.curse_participants.find_by(user_id=user_id)
        now = datetime.now(timezone.utc)
        if participant is None:
            self.curse_participants.add(
                CurseParticipant(
                    user_id=user_id,
                    subscribed_at=now,
                    last_done_at=now,
                    source_chat_ids=[chat_id],
                )
            )
            await self.curse_participants.save()
            await ctx.reply("Подписка на наказания включена.")
            return
        if chat_id not in participant.source_chat_ids:
            participant.source_chat_ids.append(chat_id)
            await self.curse_participants.save()
        await ctx.reply("Подписка на наказания уже включена.")

    @subcommand("punishment unsubscribe", description="Отписаться")
    async def unsubscribe(self, ctx: FeatureContext):
        participant = self.curse_participants.find_by(user_id=ctx.user_id)
        if participant is None:
            await ctx.reply("Подписка на наказания не найдена.")
            return
        self.curse_participants.remove(participant)
        await self.curse_participants.save()
        await ctx.reply("Подписка на наказания отключена.")

    @subcommand("punishment add <coeff:int> <title:rest>", description="Добавить наказание", admin=True)
    async def add_punishment(self, ctx: FeatureContext, coeff: int, title: str):
        title = title.strip()
        if coeff <= 0 or not title:
            raise ValidationArgumentsError()
        punishment = self.curse_punishments.add(
            CursePunishment(id=0, coeff=coeff, title=title)
        )
        await self.curse_punishments.save()
        await ctx.reply(
            f"Наказание добавлено: {punishment.id}. {punishment.coeff} -> {punishment.title}"
        )

    @subcommand("punishment remove <id:int>", description="Удалить наказание", admin=True)
    async def remove_punishment(self, ctx: FeatureContext, id: int):
        p = self.curse_punishments.find_by(id=id)
        if p is None:
            await ctx.reply("Наказание не найдено.")
            return
        self.curse_punishments.remove(p)
        await self.curse_punishments.save()
        await ctx.reply(f"Наказание {id} удалено.")

    @subcommand("done", description="Сбросить отсчёт")
    async def done_default(self, ctx: FeatureContext):
        await self._done(ctx, None)

    @subcommand("done <id:int> <count:int>", description="Засчитать часть наказания")
    async def done_with_id_and_count(self, ctx: FeatureContext, id: int, count: int):
        await self._done(ctx, id, count)

    @subcommand("done <id:int>", description="Засчитать наказание")
    async def done_with_id(self, ctx: FeatureContext, id: int):
        await self._done(ctx, id)

    async def _done(
        self,
        ctx: FeatureContext,
        punishment_id: int | None,
        count: int | None = None,
    ):
        user_id = ctx.user_id
        participant = self.curse_participants.find_by(user_id=user_id)
        if participant is None:
            await ctx.reply("Сначала подпишись на наказания.")
            return
        now = datetime.now(timezone.utc)
        if punishment_id is None:
            participant.last_done_at = now
            participant.done_words_offset = 0
            await self.curse_participants.save()
            await ctx.reply("Отсчёт наказаний сброшен.")
            return
        punishment = self.curse_punishments.find_by(id=punishment_id)
        if punishment is None:
            await ctx.reply("Наказание не найдено.")
            return
        if count is not None:
            if count <= 0:
                raise ValidationArgumentsError()
            coeff = punishment.coeff
            if coeff <= 0:
                await ctx.reply("Наказание настроено некорректно.")
                return
            if count % coeff != 0:
                lo = count - (count % coeff)
                hi = lo + coeff
                await ctx.reply(
                    "Количество должно быть кратно коэффициенту наказания "
                    f"({coeff}). Пример: {lo} или {hi}."
                )
                return
        current_count = await get_current_curse_count(
            ctx.metrics,
            user_id,
            participant.last_done_at or participant.subscribed_at,
        )
        effective_words = max(current_count - (participant.done_words_offset or 0), 0)
        if effective_words <= 0:
            await ctx.reply("Сейчас наказаний нет.")
            return

        labels = {
            "punishment_id": str(punishment.id),
            "punishment_title": punishment.title,
        }

        if count is None:
            total = punishment.coeff * effective_words
            ctx.metrics.inc("bot_curse_punishment_done_total", labels, total)
            participant.last_done_at = now
            participant.done_words_offset = 0
            await self.curse_participants.save()
            await ctx.reply(f"Наказание засчитано: {total} {punishment.title}.")
            return

        words_paid = min(count // punishment.coeff, effective_words)
        units_paid = words_paid * punishment.coeff
        remaining_words = effective_words - words_paid
        remaining_units = remaining_words * punishment.coeff

        if units_paid > 0:
            ctx.metrics.inc("bot_curse_punishment_done_total", labels, units_paid)

        if remaining_words <= 0:
            participant.last_done_at = now
            participant.done_words_offset = 0
            await self.curse_participants.save()
            await ctx.reply(
                f"Наказание засчитано: {units_paid} {punishment.title}. Долг закрыт."
            )
            return

        participant.done_words_offset = (participant.done_words_offset or 0) + words_paid
        await self.curse_participants.save()
        await ctx.reply(
            f"Засчитано: {units_paid} {punishment.title}. Осталось: {remaining_units} {punishment.title}."
        )

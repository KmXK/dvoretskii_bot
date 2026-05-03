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

    @subcommand("done <id:int>", description="Засчитать наказание")
    async def done_with_id(self, ctx: FeatureContext, id: int):
        await self._done(ctx, id)

    async def _done(self, ctx: FeatureContext, punishment_id: int | None):
        user_id = ctx.user_id
        participant = self.curse_participants.find_by(user_id=user_id)
        if participant is None:
            await ctx.reply("Сначала подпишись на наказания.")
            return
        now = datetime.now(timezone.utc)
        if punishment_id is None:
            participant.last_done_at = now
            await self.curse_participants.save()
            await ctx.reply("Отсчёт наказаний сброшен.")
            return
        punishment = self.curse_punishments.find_by(id=punishment_id)
        if punishment is None:
            await ctx.reply("Наказание не найдено.")
            return
        current_count = await get_current_curse_count(
            ctx.metrics,
            user_id,
            participant.last_done_at or participant.subscribed_at,
        )
        total = punishment.coeff * current_count
        ctx.metrics.inc(
            "bot_curse_punishment_done_total",
            {
                "punishment_id": str(punishment.id),
                "punishment_title": punishment.title,
            },
            total,
        )
        participant.last_done_at = now
        await self.curse_participants.save()
        await ctx.reply(f"Наказание засчитано: {total} {punishment.title}.")

import logging
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
    Keyboard,
    ask,
    collection,
    on_callback,
    on_init,
    subcommand,
    wizard,
)
from steward.helpers.command_validation import ValidationArgumentsError
from steward.helpers.curse_debt import (
    accrue_curse_debt,
    apply_curse_interest_until,
    build_curse_debt_report_entries,
    format_curse_debt_report,
    reduce_curse_debt,
    select_curse_punishment_for_day,
    today_msk,
)
from steward.helpers.validation import Error, validate_message_text


_MSK = ZoneInfo("Europe/Minsk")
logger = logging.getLogger(__name__)

_PUNISHMENT_TITLE_QUESTION = 'Введите название наказания, например: "отжимания", "приседания"'
_PUNISHMENT_COEFF_QUESTION = (
    "Введите сколько единиц наказания выполнять за один мат, например 1 отжимание -> 5 приседаний"
)
_PUNISHMENT_WEIGHT_QUESTION = (
    "Введите весовой коэффициент данного наказания. Используется при выборе наказания дня. "
    "Например, вес отжиманий: 2, вес приседаний: 1, "
    "следовательно отжимания будут наказанием дня в 2 раза чаще приседаний"
)
_PUNISHMENT_INTEREST_QUESTION = (
    "Введите накопительный процент по наказанию. Если наказание не было выполнено день в день, "
    "то в следующий день наказание нужно будет выполнить с процентами. "
    "Например, 10 отжиманий было перенесено на следующий день, процент = 10, "
    "тогда на следующий день ты будешь должен выполнить 11 отжиманий, а не 10"
)


def _parse_words(raw: str) -> list[str]:
    out, seen = [], set()
    for word in raw.split():
        norm = word.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _parse_positive_int(value: str) -> int | Error:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return Error("Введи целое число больше нуля.")
    if parsed <= 0:
        return Error("Введи целое число больше нуля.")
    return parsed


def _parse_non_negative_float(value: str) -> float | Error:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return Error("Введи число не меньше нуля.")
    if parsed < 0:
        return Error("Введи число не меньше нуля.")
    return parsed


def _parse_positive_float(value: str) -> float | Error:
    parsed = _parse_non_negative_float(value)
    if isinstance(parsed, Error):
        return parsed
    if parsed <= 0:
        return Error("Введи число больше нуля.")
    return parsed


def _parse_punishment_field_from_state(value: str, state: dict):
    return _parse_punishment_field(state.get("field"), value)


def _normalize_punishment_title(title: str) -> str:
    return " ".join(title.strip().split()).lower().capitalize()


class CurseFeature(Feature):
    command = "curse"
    description = "Маты и наказания"

    curse_words = collection("curse_words")
    curse_ignore_words = collection("curse_ignore_words")
    curse_punishments = collection("curse_punishments")
    curse_punishment_days = collection("curse_punishment_days")
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
        if accrue_curse_debt(self.repository, ctx.user_id, n, today_msk()):
            await self.repository.save()
        await ctx.reply(f"Добавил {n} плохих слов.")

    @subcommand("word_list", description="Список матерных слов")
    async def show_word_list(self, ctx: FeatureContext):
        words = sorted(self.curse_words.all())
        if not words:
            await ctx.reply("Список матерных слов пуст.")
            return
        await ctx.reply("Матерные слова:\n\n" + "\n".join(words))

    @subcommand("word_list add <words:rest>", description="Добавить слова")
    async def add_words(self, ctx: FeatureContext, words: str):
        if not await self._require_curse_admin(ctx):
            return
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()
        added = self.curse_words.add_many(items)
        if not added:
            await ctx.reply("Все слова уже есть в списке.")
            return
        await self.curse_words.save()
        await ctx.reply("Добавлены слова: " + ", ".join(added))

    @subcommand("word_list remove <words:rest>", description="Удалить слова")
    async def remove_words(self, ctx: FeatureContext, words: str):
        if not await self._require_curse_admin(ctx):
            return
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

    @subcommand("ignore_list add <words:rest>", description="Добавить исключения")
    async def add_ignore_words(self, ctx: FeatureContext, words: str):
        if not await self._require_curse_admin(ctx):
            return
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()
        added = self.curse_ignore_words.add_many(items)
        if not added:
            await ctx.reply("Все исключения уже есть в списке.")
            return
        await self.curse_ignore_words.save()
        await ctx.reply("Добавлены исключения: " + ", ".join(added))

    @subcommand("ignore_list remove <words:rest>", description="Удалить исключения")
    async def remove_ignore_words(self, ctx: FeatureContext, words: str):
        if not await self._require_curse_admin(ctx):
            return
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
        cards = [self._punishment_text(p) for p in items]
        await ctx.reply("Наказания:\n\n" + "\n\n".join(cards))

    @subcommand("", description="Наказания сегодня")
    @subcommand("punishment today")
    async def punishment_today(self, ctx: FeatureContext):
        if not self.curse_punishments.all():
            await ctx.reply("Наказания ещё не настроены. Добавь их через /curse punishment add.")
            return
        punishment, day_changed = select_curse_punishment_for_day(
            self.repository,
            today_msk(),
        )
        interest_changed = apply_curse_interest_until(self.repository, today_msk())
        if day_changed or interest_changed:
            await self.repository.save()
        entries = build_curse_debt_report_entries(self.repository, ctx.chat_id)
        report = format_curse_debt_report(entries)
        if punishment is None:
            await ctx.reply(
                "Наказание дня не выбрано: нет наказаний с положительным весом.\n\n"
                + report
            )
            return
        await ctx.reply("Наказание дня:\n\n" + self._punishment_text(punishment) + "\n\n" + report)

    @subcommand("subscribe", description="Подписаться")
    @subcommand("punishment subscribe")
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

    @subcommand("unsubscribe", description="Отписаться")
    @subcommand("punishment unsubscribe")
    async def unsubscribe(self, ctx: FeatureContext):
        participant = self.curse_participants.find_by(user_id=ctx.user_id)
        if participant is None:
            await ctx.reply("Подписка на наказания не найдена.")
            return
        self.curse_participants.remove(participant)
        await self.curse_participants.save()
        await ctx.reply("Подписка на наказания отключена.")

    @subcommand("punishment add", description="Добавить наказание")
    async def start_add_punishment(self, ctx: FeatureContext):
        if not await self._require_curse_admin(ctx):
            return
        await self.start_wizard("curse:punishment:add", ctx)

    @wizard(
        "curse:punishment:add",
        ask("title", _PUNISHMENT_TITLE_QUESTION),
        ask(
            "coeff",
            _PUNISHMENT_COEFF_QUESTION,
            validator=validate_message_text([_parse_positive_int]),
        ),
        ask(
            "selection_weight",
            _PUNISHMENT_WEIGHT_QUESTION,
            validator=validate_message_text([_parse_positive_float]),
        ),
        ask(
            "interest_percent",
            _PUNISHMENT_INTEREST_QUESTION,
            validator=validate_message_text([_parse_non_negative_float]),
        ),
    )
    async def punishment_add_done(
        self,
        ctx: FeatureContext,
        title: str,
        coeff: int,
        selection_weight: float,
        interest_percent: float,
    ):
        if not await self._require_curse_admin(ctx):
            return
        title = _normalize_punishment_title(title)
        if not title:
            await ctx.reply("Название наказания не может быть пустым.")
            return
        punishment = self.curse_punishments.add(
            CursePunishment(
                id=0,
                coeff=coeff,
                title=title,
                interest_percent=interest_percent,
                selection_weight=selection_weight,
            )
        )
        await self.curse_punishments.save()
        logger.info(
            "curse punishment added rule_id=%s title=%r coeff=%s interest=%s weight=%s admin_user_id=%s",
            punishment.id,
            punishment.title,
            punishment.coeff,
            punishment.interest_percent,
            punishment.selection_weight,
            ctx.user_id,
        )
        await ctx.reply("Наказание добавлено:\n\n" + self._punishment_text(punishment))

    @subcommand("punishment add <coeff:int> <title:rest>")
    async def add_punishment(self, ctx: FeatureContext, coeff: int, title: str):
        if not await self._require_curse_admin(ctx):
            return
        title = _normalize_punishment_title(title)
        if coeff <= 0 or not title:
            raise ValidationArgumentsError()
        punishment = self.curse_punishments.add(
            CursePunishment(id=0, coeff=coeff, title=title)
        )
        await self.curse_punishments.save()
        await ctx.reply("Наказание добавлено:\n\n" + self._punishment_text(punishment))

    @subcommand("punishment edit <id:int>", description="Редактировать наказание")
    async def edit_punishment(self, ctx: FeatureContext, id: int):
        if not await self._require_curse_admin(ctx):
            return
        punishment = self.curse_punishments.find_by(id=id)
        if punishment is None:
            await ctx.reply("Наказание не найдено.")
            return
        await ctx.reply(
            self._punishment_edit_text(punishment),
            keyboard=self._punishment_edit_keyboard(punishment),
        )

    @on_callback(
        "curse:punishment_edit",
        schema="<id:int>|<field:literal[title|coeff|weight|interest|delete]>",
    )
    async def cb_punishment_edit(self, ctx: FeatureContext, id: int, field: str):
        if not await self._require_curse_admin(ctx, toast=True):
            return
        punishment = self.curse_punishments.find_by(id=id)
        if punishment is None:
            await ctx.toast("Наказание не найдено.")
            return
        if field == "delete":
            message = self._remove_punishment(id, ctx.user_id)
            if message is None:
                await self.curse_punishments.save()
                await ctx.edit(f"Наказание {id} удалено.", keyboard=None)
            else:
                await ctx.toast(message, alert=True)
            return
        await self.start_wizard("curse:punishment:edit_field", ctx, id=id, field=field)

    @wizard(
        "curse:punishment:edit_field",
        ask(
            "value",
            lambda state: _edit_field_question(state["field"]),
            validator=validate_message_text([_parse_punishment_field_from_state]),
        ),
    )
    async def punishment_edit_field_done(
        self,
        ctx: FeatureContext,
        id: int,
        field: str,
        value,
    ):
        if not await self._require_curse_admin(ctx):
            return
        punishment = self.curse_punishments.find_by(id=id)
        if punishment is None:
            await ctx.reply("Наказание не найдено.")
            return

        parsed = _parse_punishment_field(field, value)
        if isinstance(parsed, Error):
            await ctx.reply(parsed.message)
            return

        old = _punishment_field_value(punishment, field)
        if field == "title":
            punishment.title = parsed
        elif field == "coeff":
            punishment.coeff = parsed
        elif field == "weight":
            punishment.selection_weight = parsed
        elif field == "interest":
            if apply_curse_interest_until(self.repository, today_msk()):
                await self.repository.save()
            punishment.interest_percent = parsed
        else:
            await ctx.reply("Неизвестное поле.")
            return

        await self.curse_punishments.save()
        logger.info(
            "curse punishment field changed rule_id=%s field=%s old=%r new=%r admin_user_id=%s",
            punishment.id,
            field,
            old,
            parsed,
            ctx.user_id,
        )
        await ctx.reply(
            f"Наказание {id} изменено.\n\n{self._punishment_edit_text(punishment)}"
        )

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
        if punishment_id is None:
            debts = [
                debt for debt in self.repository.db.curse_punishment_debts
                if debt.user_id == user_id
            ]
            for debt in debts:
                self.repository.db.curse_punishment_debts.remove(debt)
            await self.curse_participants.save()
            await ctx.reply("Все наказания сброшены.")
            return
        punishment = self.curse_punishments.find_by(id=punishment_id)
        if punishment is None:
            await ctx.reply("Наказание не найдено.")
            return
        if count is not None and count <= 0:
            raise ValidationArgumentsError()

        paid, remaining = reduce_curse_debt(self.repository, user_id, punishment.id, count)
        if paid <= 0:
            await ctx.reply("Сейчас наказаний нет.")
            return

        labels = {
            "punishment_id": str(punishment.id),
            "punishment_title": punishment.title,
        }
        ctx.metrics.inc("bot_curse_punishment_done_total", labels, paid)
        await self.curse_participants.save()

        if remaining <= 0:
            await ctx.reply(
                f"Наказание засчитано: {paid} {punishment.title}. Долг закрыт."
            )
            return

        await ctx.reply(
            f"Засчитано: {paid} {punishment.title}. Осталось: {remaining} {punishment.title}."
        )

    def _punishment_edit_text(self, punishment: CursePunishment) -> str:
        return self._punishment_text(punishment)

    def _punishment_text(self, punishment: CursePunishment) -> str:
        return (
            f"Наказание #{punishment.id}\n\n"
            f"Название: {punishment.title}\n"
            f"Коэффициент: {punishment.coeff}\n"
            f"Весовой коэффициент в наказании дня: {punishment.selection_weight}\n"
            f"Ежедневный процент на долг: {punishment.interest_percent}%"
        )

    def _punishment_edit_keyboard(self, punishment: CursePunishment) -> Keyboard:
        edit = self.cb("curse:punishment_edit")
        return Keyboard.grid(
            [
                [
                    edit.button("Название", id=punishment.id, field="title"),
                    edit.button("Коэффициент", id=punishment.id, field="coeff"),
                ],
                [
                    edit.button("Вес", id=punishment.id, field="weight"),
                    edit.button("Процент", id=punishment.id, field="interest"),
                ],
                [edit.button("Удалить", id=punishment.id, field="delete")],
            ]
        )

    def _is_curse_admin(self, ctx: FeatureContext) -> bool:
        return ctx.repository.is_chat_admin(ctx.user_id, ctx.chat_id)

    async def _require_curse_admin(
        self,
        ctx: FeatureContext,
        *,
        toast: bool = False,
    ) -> bool:
        if self._is_curse_admin(ctx):
            return True
        if toast:
            await ctx.toast("Недостаточно прав.")
        else:
            await ctx.reply("Недостаточно прав.")
        return False

    def _remove_punishment(self, id: int, admin_user_id: int) -> str | None:
        punishment = self.curse_punishments.find_by(id=id)
        if punishment is None:
            return "Наказание не найдено."
        has_debt = any(
            debt.rule_id == id and debt.punishment_count > 0
            for debt in self.repository.db.curse_punishment_debts
        )
        if has_debt:
            return "Нельзя удалить наказание: по нему есть открытый долг."
        is_today_punishment = any(
            day.date == today_msk().isoformat() and day.rule_id == id
            for day in self.repository.db.curse_punishment_days
        )
        if is_today_punishment:
            return "Нельзя удалить наказание: оно выбрано наказанием дня."
        self.curse_punishments.remove(punishment)
        logger.info(
            "curse punishment removed rule_id=%s title=%r admin_user_id=%s",
            punishment.id,
            punishment.title,
            admin_user_id,
        )
        return None


def _edit_field_question(field: str) -> str:
    if field == "title":
        return _PUNISHMENT_TITLE_QUESTION
    if field == "coeff":
        return _PUNISHMENT_COEFF_QUESTION
    if field == "weight":
        return _PUNISHMENT_WEIGHT_QUESTION
    if field == "interest":
        return _PUNISHMENT_INTEREST_QUESTION
    return "Новое значение?"


def _parse_punishment_field(field: str, value):
    if field == "title":
        title = str(value).strip()
        if not title:
            return Error("Название наказания не может быть пустым.")
        return title
    if field == "coeff":
        return _parse_positive_int(str(value))
    if field == "weight":
        return _parse_positive_float(str(value))
    if field == "interest":
        return _parse_non_negative_float(str(value))
    return Error("Неизвестное поле.")


def _punishment_field_value(punishment: CursePunishment, field: str):
    if field == "title":
        return punishment.title
    if field == "coeff":
        return punishment.coeff
    if field == "weight":
        return punishment.selection_weight
    if field == "interest":
        return punishment.interest_percent
    return None

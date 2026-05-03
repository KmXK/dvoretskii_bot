"""Suggestion lifecycle delayed actions: 12h admin hint and 48h expiry."""
import datetime
import logging
from dataclasses import dataclass

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark

logger = logging.getLogger(__name__)

ADMIN_HINT_HOURS = 12
EXPIRY_HOURS = 48


@dataclass
@class_mark("generator/bill_suggestion_admin_hint")
class BillSuggestionAdminHintGenerator(Generator):
    fire_at: datetime.datetime

    def get_next(self, now: datetime.datetime):
        return self.fire_at


@dataclass
@class_mark("generator/bill_suggestion_expire")
class BillSuggestionExpireGenerator(Generator):
    fire_at: datetime.datetime

    def get_next(self, now: datetime.datetime):
        return self.fire_at


def _remove_self(context: DelayedActionContext, action):
    context.repository.db.delayed_actions = [
        a for a in context.repository.db.delayed_actions if a is not action
    ]


@dataclass
@class_mark("delayed_action/bill_suggestion_admin_hint")
class BillSuggestionAdminHintAction(DelayedAction):
    suggestion_id: str
    generator: BillSuggestionAdminHintGenerator

    async def execute(self, context: DelayedActionContext):
        repository = context.repository
        suggestion = repository.get_bill_suggestion(self.suggestion_id)
        _remove_self(context, self)

        from steward.data.models.bill_v2 import SuggestionStatus

        if suggestion is None or suggestion.status != SuggestionStatus.PENDING:
            await repository.save()
            return

        if suggestion.approval_chat_id and suggestion.approval_message_id:
            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Одобрить", callback_data=f"bills:suggest_approve|{suggestion.id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"bills:suggest_reject|{suggestion.id}"),
                ]])
                await context.bot.edit_message_reply_markup(
                    chat_id=suggestion.approval_chat_id,
                    message_id=suggestion.approval_message_id,
                    reply_markup=keyboard,
                )
                # Append admin hint as a follow-up message
                await context.bot.send_message(
                    chat_id=suggestion.approval_chat_id,
                    text=f"_(Администратор тоже может одобрить это предложение)_",
                    parse_mode="Markdown",
                    reply_to_message_id=suggestion.approval_message_id,
                )
            except Exception as e:
                logger.warning("Failed to send admin hint for suggestion %s: %s", self.suggestion_id, e)

        await repository.save()


@dataclass
@class_mark("delayed_action/bill_suggestion_expire")
class BillSuggestionExpireAction(DelayedAction):
    suggestion_id: str
    generator: BillSuggestionExpireGenerator

    async def execute(self, context: DelayedActionContext):
        repository = context.repository
        suggestion = repository.get_bill_suggestion(self.suggestion_id)
        _remove_self(context, self)

        from steward.data.models.bill_v2 import SuggestionStatus

        if suggestion is None or suggestion.status != SuggestionStatus.PENDING:
            await repository.save()
            return

        suggestion.status = SuggestionStatus.EXPIRED
        suggestion.decided_at = datetime.datetime.now()

        proposer = repository.get_bill_person(suggestion.proposed_by_person_id)
        bill = repository.get_bill_v2(suggestion.bill_id)
        bill_name = bill.name if bill else f"#{suggestion.bill_id}"

        if proposer:
            from steward.helpers.bills_notifications import send_bill_notification
            await send_bill_notification(
                context.bot, repository, proposer,
                f"⏰ Предложение в «{bill_name}» истекло ({EXPIRY_HOURS}ч без ответа).",
                initiated_chat_id=suggestion.origin_chat_id,
            )

        await repository.save()


def schedule_suggestion_lifecycle(repository, suggestion_id: str) -> None:
    """Schedule admin hint (12h) and expiry (48h) actions for a suggestion."""
    now = datetime.datetime.now()

    hint_action = BillSuggestionAdminHintAction(
        suggestion_id=suggestion_id,
        generator=BillSuggestionAdminHintGenerator(
            fire_at=now + datetime.timedelta(hours=ADMIN_HINT_HOURS)
        ),
    )
    expire_action = BillSuggestionExpireAction(
        suggestion_id=suggestion_id,
        generator=BillSuggestionExpireGenerator(
            fire_at=now + datetime.timedelta(hours=EXPIRY_HOURS)
        ),
    )
    repository.db.delayed_actions.append(hint_action)
    repository.db.delayed_actions.append(expire_action)

"""Revoke Google Sheet permissions when a BillDraftEdit TTL expires."""
import datetime
import logging
from dataclasses import dataclass

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark

logger = logging.getLogger(__name__)


@dataclass
@class_mark("generator/bill_draft_expire")
class BillDraftExpireGenerator(Generator):
    fire_at: datetime.datetime

    def get_next(self, now: datetime.datetime):
        return self.fire_at


@dataclass
@class_mark("delayed_action/bill_draft_expire")
class BillDraftExpireAction(DelayedAction):
    draft_id: str
    generator: BillDraftExpireGenerator

    async def execute(self, context: DelayedActionContext):
        repository = context.repository
        draft = repository.get_bill_draft_edit(self.draft_id)

        context.repository.db.delayed_actions = [
            a for a in context.repository.db.delayed_actions if a is not self
        ]

        if draft is None or draft.merged:
            await repository.save()
            return

        if draft.sheet_file_id:
            try:
                from steward.helpers.google_drive import revoke_bill_edit_sheet
                await revoke_bill_edit_sheet(draft.sheet_file_id)
            except Exception as e:
                logger.warning("Failed to revoke sheet permissions for draft %s: %s", self.draft_id, e)

        repository.cleanup_expired_drafts()
        await repository.save()


def schedule_draft_expire(repository, draft_id: str, expires_at: datetime.datetime) -> None:
    """Schedule sheet revocation at expires_at."""
    action = BillDraftExpireAction(
        draft_id=draft_id,
        generator=BillDraftExpireGenerator(fire_at=expires_at),
    )
    repository.db.delayed_actions.append(action)

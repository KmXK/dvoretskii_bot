import datetime
from dataclasses import dataclass, field

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark


@dataclass
@class_mark("generator/reminder")
class ReminderGenerator(Generator):
    next_fire: datetime.datetime
    interval_seconds: int | None = None
    repeat_remaining: int | None = None

    def get_next(self, now: datetime.datetime):
        if self.next_fire.tzinfo is None:
            self.next_fire = self.next_fire.replace(tzinfo=datetime.timezone.utc)
        return self.next_fire


@dataclass
@class_mark("delayed_action/reminder")
class ReminderDelayedAction(DelayedAction):
    id: str
    chat_id: int
    user_id: int
    text: str
    created_at: datetime.datetime
    generator: ReminderGenerator
    fired_count: int = 0

    async def execute(self, context: DelayedActionContext):
        await context.bot.send_message(self.chat_id, f"🔔 {self.text}")
        self.fired_count += 1

        gen = self.generator
        if gen.interval_seconds and (gen.repeat_remaining is None or gen.repeat_remaining > 1):
            gen.next_fire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=gen.interval_seconds)
            if gen.repeat_remaining is not None:
                gen.repeat_remaining -= 1
            await context.repository.save()
        else:
            context.repository.db.delayed_actions.remove(self)
            context.repository.db.completed_reminders.append(CompletedReminder(
                id=self.id,
                chat_id=self.chat_id,
                user_id=self.user_id,
                text=self.text,
                created_at=self.created_at,
                completed_at=datetime.datetime.now(datetime.timezone.utc),
                fired_count=self.fired_count,
            ))
            await context.repository.save()


@dataclass
@class_mark("reminder/completed")
class CompletedReminder:
    id: str
    chat_id: int
    user_id: int
    text: str
    created_at: datetime.datetime
    completed_at: datetime.datetime
    fired_count: int = 1

from dataclasses import dataclass

from steward.delayed_action.base import DelayedAction
from steward.helpers.class_mark import class_mark


@dataclass
class MessageData:
    chat_id: int
    msg_id: int


@dataclass
@class_mark("delayed_action/send_message")
class SendMessageDelayedAction(DelayedAction):
    to_chat_id: int
    data: str | MessageData

    async def execute(self, context):
        if isinstance(self.data, str):
            await context.bot.send_message(self.to_chat_id, self.data)
        else:
            await context.bot.copy_message(
                self.to_chat_id,
                self.data.chat_id,
                self.data.msg_id,
            )

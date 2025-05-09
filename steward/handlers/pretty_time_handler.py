import logging

from steward.bot.context import ChatBotContext
from steward.delayed_action.pretty_time import PrettyTimeDelayedAction
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler

logger = logging.getLogger(__name__)


@CommandHandler("pretty_time", only_admin=True, arguments_template=r"(?P<action>.*)?")
class PrettyTimeHandler(Handler):
    async def chat(
        self,
        context: ChatBotContext,
        action: str,
    ):
        chat_id = context.message.chat_id
        delayed_action = next(
            filter(
                lambda x: (
                    isinstance(x, PrettyTimeDelayedAction) and x.chat_id == chat_id
                ),
                self.repository.db.delayed_actions,
            ),
            None,
        )

        if action == "delete":
            logger.info("deleting: %s", delayed_action)
            if delayed_action is not None:
                self.repository.db.delayed_actions.remove(delayed_action)
                await self.repository.save()
            return True

        if delayed_action is None:
            self.repository.db.delayed_actions.append(
                PrettyTimeDelayedAction(chat_id=chat_id)
            )
            await self.repository.save()

            # await context.message.reply_text("Добавил")

        return True

    def help(self) -> str | None:
        return "/pretty_time - добавить вывод красивого времени"

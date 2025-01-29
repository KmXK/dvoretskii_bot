from typing import TypeGuard

from steward.handlers.handler import CommandHandler, Handler


def make_help_message(handlers: list[Handler], is_admin: bool):
    def check_help_msg(h: str | None) -> TypeGuard[str]:
        return h is not None

    help_msgs = [
        *filter(
            check_help_msg,
            (
                handler.help()
                for handler in handlers
                if handler.help and (is_admin or not handler.only_for_admin)
            ),
        ),
    ]
    help_msgs.sort()

    if len(help_msgs) == 0:
        return "Список команд пуст"

    return "\n".join(["Список команд: ", "", *help_msgs])


@CommandHandler("help")
class HelpHandler(Handler):
    def __init__(self, handlers, repository):
        self.repository = repository
        self.helpMessage = make_help_message(handlers, False)
        self.adminHelpMessage = make_help_message(handlers, True)

    async def chat(self, update, context):
        if self.repository.is_admin(update.message.from_user.id):
            await update.message.reply_text(self.adminHelpMessage)
        else:
            await update.message.reply_text(self.helpMessage)

    def help(self):
        return "/help - показать список команд"

from handlers.handler import CommandHandler, Handler


def make_help_message(handlers, is_admin):
    handlers = [
        handler.help() for handler in handlers if not isinstance(handler, HelpHandler)
        and handler.help
        and (is_admin or not handler.only_for_admin)
    ]
    handlers.sort()

    return '\n'.join([
        'Список команд: ', '',
        *filter(lambda h: len(h) > 0, handlers)
    ])


@CommandHandler('help')
class HelpHandler(Handler):
    def __init__(self, handlers, repository):
        self.repository = repository
        self.helpMessage = make_help_message(handlers, False)
        self.adminHelpMessage = make_help_message(handlers, True)

    async def chat(self, update, context):
        if self.repository.is_admin(update.message.from_user.id):
            await update.message.reply_text(self.adminHelpMessage)
            print(self.adminHelpMessage)
        else:
            await update.message.reply_text(self.helpMessage)
            print(self.helpMessage)

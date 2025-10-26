from telegram import Update


class UnsupportedUpdateType(Exception):
    pass


def get_message(update: Update):
    if update.message:
        return update.message
    elif update.edited_message:
        return update.edited_message
    elif update.callback_query:
        return update.callback_query.message
    raise UnsupportedUpdateType("Unsupported update type")


def get_from_user(update: Update):
    if update.message:
        return update.message.from_user
    elif update.edited_message:
        return update.edited_message.from_user
    elif update.callback_query:
        return update.callback_query.from_user
    elif update.message_reaction:
        return update.message_reaction.user
    raise UnsupportedUpdateType("Unsupported update type")

from telegram import Update


def get_message(update: Update):
    if update.message:
        return update.message
    elif update.edited_message:
        return update.edited_message
    elif update.callback_query:
        return update.callback_query.message
    raise Exception("Unsupported update type")


def get_from_user(update: Update):
    if update.message:
        return update.message.from_user
    elif update.edited_message:
        return update.edited_message.from_user
    elif update.callback_query:
        return update.callback_query.from_user
    raise Exception("Unsupported update type")

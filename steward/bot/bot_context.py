from dataclasses import dataclass

from telegram import CallbackQuery, Message, Update
from telegram.ext import ContextTypes

from steward.data.repository import Repository


@dataclass
class BotContext:
    repository: Repository
    update: Update
    tg_context: ContextTypes.DEFAULT_TYPE


@dataclass
class ChatBotContext(BotContext):
    message: Message


@dataclass
class CallbackBotContext(BotContext):
    callback_query: CallbackQuery

from dataclasses import dataclass

from telegram import CallbackQuery, Message, Update
from telegram.ext import ContextTypes

from steward.data.repository import Repository


@dataclass
class BotContext:
    repository: Repository


@dataclass
class BotActionContext(BotContext):
    update: Update
    tg_context: ContextTypes.DEFAULT_TYPE


@dataclass
class ChatBotContext(BotActionContext):
    message: Message


@dataclass
class CallbackBotContext(BotActionContext):
    callback_query: CallbackQuery

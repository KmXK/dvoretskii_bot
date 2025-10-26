from dataclasses import dataclass

from telegram import CallbackQuery, Message, MessageReactionUpdated, Update
from telegram.ext import ContextTypes, ExtBot
from telethon import TelegramClient

from steward.data.repository import Repository


@dataclass
class BotContext:
    repository: Repository

    bot: ExtBot[None]
    client: TelegramClient


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


@dataclass
class ReactionBotContext(BotActionContext):
    message_reaction: MessageReactionUpdated


@dataclass
class DelayedActionContext(BotContext):
    pass

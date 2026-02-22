from telegram.ext import ExtBot

from steward.bot.context import CallbackBotContext, ChatBotContext, ReactionBotContext
from steward.data.repository import Repository


class Handler:
    # аккуратно с атрибутом класса, сделал его как значение по умолчанию
    # выносить в конструктор не хочу, чтобы не вызывать super везде
    # но при присвоении значения в дочерних объектах, они создают новый атрибут,
    # а не перезаписывают его тут
    only_for_admin = False

    # initialized externally (# TODO: перепридумать!)
    repository: Repository
    bot: ExtBot[None]

    # to initialize handler
    async def init(self):
        pass

    async def chat(self, context: ChatBotContext) -> bool:
        """Chat message handler"""
        return False

    async def callback(self, context: CallbackBotContext) -> bool:
        """Callback handler"""
        return False

    async def reaction(self, context: ReactionBotContext) -> bool:
        """Reaction handler"""
        return False

    def help(self) -> str | None:
        return None

    def prompt(self) -> str | None:
        """AI prompt for command routing — detailed instructions for the AI model."""
        return None
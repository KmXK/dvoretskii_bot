from telegram import Update
from telegram.ext import ContextTypes


class Handler:
    # аккуратно с атрибутом класса, сделал его как значение по умолчанию
    # выносить в конструктор не хочу, чтобы не вызывать super везде
    # но при присвоении значения в дочерних объектах, они создают новый атрибут,
    # а не перезаписывают его тут
    only_for_admin = False

    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Chat message handler"""
        return False

    async def callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Callback handler"""
        return False

    def help(self) -> str | None:
        return None

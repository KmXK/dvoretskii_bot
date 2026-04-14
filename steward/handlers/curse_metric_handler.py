from steward.bot.context import ChatBotContext
from steward.handlers.handler import Handler


class CurseMetricHandler(Handler):
    async def chat(self, context: ChatBotContext) -> bool:
        text = context.message.text
        if not text or text.startswith("/"):
            return False

        if getattr(context.message, "forward_origin", None) is not None:
            return False

        curse_words = self.repository.db.curse_words
        if not curse_words:
            return False

        count = sum(1 for token in text.split() if token.lower() in curse_words)
        if count > 0:
            context.metrics.inc("bot_curse_words_total", value=count)

        return False

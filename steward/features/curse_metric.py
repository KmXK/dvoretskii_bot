from steward.framework import Feature, FeatureContext, collection, on_message


class CurseMetricFeature(Feature):
    curse_words = collection("curse_words")

    @on_message
    async def count(self, ctx: FeatureContext) -> bool:
        if ctx.message is None:
            return False
        text = ctx.message.text
        if not text or text.startswith("/"):
            return False
        if getattr(ctx.message, "forward_origin", None) is not None:
            return False
        words = self.curse_words.all()
        if not words:
            return False
        count = sum(1 for token in text.split() if token.lower() in words)
        if count > 0:
            ctx.metrics.inc("bot_curse_words_total", value=count)
        return False

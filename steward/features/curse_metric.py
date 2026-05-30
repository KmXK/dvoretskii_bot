from steward.framework import Feature, FeatureContext, collection, on_message
from steward.helpers.curse_detector import CurseDetector


class CurseMetricFeature(Feature):
    curse_words = collection("curse_words")
    curse_ignore_words = collection("curse_ignore_words")

    def __init__(self):
        super().__init__()
        self._detector = CurseDetector()

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
        count = self._detector.count(
            text,
            set(words),
            set(self.curse_ignore_words.all()),
        )
        if count > 0:
            ctx.metrics.inc("bot_curse_words_total", value=count)
        return False

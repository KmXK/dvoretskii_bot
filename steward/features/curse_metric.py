from steward.framework import Feature, FeatureContext, collection, on_message
from steward.helpers.curse_processing import process_curse_text


def _message_text_or_caption(message) -> str | None:
    for value in (getattr(message, "text", None), getattr(message, "caption", None)):
        if isinstance(value, str) and value:
            return value
    return None


class CurseMetricFeature(Feature):
    curse_words = collection("curse_words")
    curse_ignore_words = collection("curse_ignore_words")

    @on_message
    async def count(self, ctx: FeatureContext) -> bool:
        if ctx.message is None:
            return False
        text = _message_text_or_caption(ctx.message)
        if not text or text.startswith("/"):
            return False
        if getattr(ctx.message, "forward_origin", None) is not None:
            return False
        await process_curse_text(
            self.repository,
            ctx.metrics,
            user_id=ctx.user_id,
            text=text,
            source_message=ctx.message,
        )
        return False

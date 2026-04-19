from steward.framework import Feature, FeatureContext, on_message
from steward.helpers.ai_context import (
    execute_ai_request,
    execute_ai_request_streaming,
    get_ai_handler,
    get_ai_stream_handler,
)


class AiRelatedFeature(Feature):
    @on_message
    async def reply_thread(self, ctx: FeatureContext) -> bool:
        if (
            ctx.message is None
            or not ctx.message.text
            or not ctx.message.reply_to_message
        ):
            return False
        key = f"{ctx.message.chat.id}_{ctx.message.reply_to_message.id}"
        if key not in ctx.repository.db.ai_messages:
            return False
        ai_message = ctx.repository.db.ai_messages[key]
        stream_call = get_ai_stream_handler(ai_message.handler)
        if stream_call:
            await execute_ai_request_streaming(
                ctx, ctx.message.text, stream_call, ai_message.handler
            )
            return True
        ai_call = get_ai_handler(ai_message.handler)
        if not ai_call:
            return False
        await execute_ai_request(ctx, ctx.message.text, ai_call, ai_message.handler)
        return True

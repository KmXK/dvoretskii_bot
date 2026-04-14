from steward.session.context import ChatStepContext


async def fill_or_prompt(
    context: ChatStepContext,
    key: str,
    prompt: str,
    **reply_kwargs,
) -> bool:
    """
    Advance immediately if `key` is already in session_context (pre-seeded from inline args).
    Otherwise prompt once, then read the next text message as the value.
    """
    sc = context.session_context
    if key in sc:
        return True
    if f"__awaiting_{key}__" in sc:
        value = (context.message.text or "").strip()
        if not value or value.startswith("/"):
            return False
        sc[key] = value
        return True
    await context.message.reply_text(prompt, **reply_kwargs)
    sc[f"__awaiting_{key}__"] = True
    return False

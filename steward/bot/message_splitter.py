from telegram.constants import MessageLimit

MAX_LEN = MessageLimit.MAX_TEXT_LENGTH


def split_message(text: str) -> list[str]:
    if len(text) <= MAX_LEN:
        return [text]

    chunks = []
    while text:
        if len(text) <= MAX_LEN:
            chunks.append(text)
            break

        split_at = text.rfind("\n\n", 0, MAX_LEN)
        if split_at == -1:
            split_at = text.rfind("\n", 0, MAX_LEN)
        if split_at == -1:
            split_at = text.rfind(" ", 0, MAX_LEN)
        if split_at == -1:
            split_at = MAX_LEN

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


def patch_bot_send_message(bot):
    original = bot.send_message

    async def send_message_split(*args, **kwargs):
        text = kwargs.get("text") or (args[1] if len(args) > 1 else None)
        if not text or len(text) <= MAX_LEN:
            return await original(*args, **kwargs)

        chat_id = kwargs.get("chat_id") or (args[0] if args else None)
        parts = split_message(text)

        kwargs.pop("text", None)
        clean_args = args[2:] if len(args) > 1 else args[1:] if args else ()

        last_message = None
        for part in parts:
            last_message = await original(chat_id, part, *clean_args, **kwargs)
        return last_message

    bot.send_message = send_message_split

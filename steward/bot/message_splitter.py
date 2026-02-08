from telegram.constants import MessageLimit
from telegram.ext import ExtBot

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


_original_send_message = ExtBot.send_message


async def _splitting_send_message(self, *args, **kwargs):
    text = kwargs.get("text") or (args[1] if len(args) > 1 else None)
    if not text or len(text) <= MAX_LEN:
        return await _original_send_message(self, *args, **kwargs)

    chat_id = kwargs.get("chat_id") or (args[0] if args else None)
    parts = split_message(text)

    if "text" in kwargs:
        kwargs.pop("text")
        clean_args = args
    else:
        clean_args = (args[0],) + args[2:] if len(args) > 1 else args

    last_message = None
    for part in parts:
        last_message = await _original_send_message(self, *clean_args, text=part, **kwargs)
    return last_message


def patch_send_message():
    ExtBot.send_message = _splitting_send_message

import html
import re

from telegram import MessageEntity

from steward.data.models.reward import Reward
from steward.helpers.validation import Error


def format_reward_emoji(reward: Reward) -> str:
    if reward.custom_emoji_id:
        return (
            f'<tg-emoji emoji-id="{reward.custom_emoji_id}">'
            f"{html.escape(reward.emoji)}"
            f"</tg-emoji>"
        )
    return html.escape(reward.emoji)


def format_reward_html(reward: Reward) -> str:
    return f"{format_reward_emoji(reward)} — {html.escape(reward.name)}"


def format_lined_list_html(items: list[tuple[int, str]], delimiter: str = ". ") -> str:
    max_length = max(len(str(item[0])) for item in items)
    return "\n".join(
        f"<code>{str(item[0]).rjust(max_length)}</code>{delimiter}{item[1]}"
        for item in items
    )


def extract_emoji(update, session_context):
    msg = update.message
    if not msg or not msg.text:
        return Error("Отправьте эмоджи")

    custom_emoji_id = None
    if msg.entities:
        for entity in msg.entities:
            if entity.type == MessageEntity.CUSTOM_EMOJI:
                custom_emoji_id = entity.custom_emoji_id
                break

    if not custom_emoji_id and re.search(r"[a-zA-Zа-яА-ЯёЁ0-9]", msg.text):
        return Error("Отправьте эмоджи, а не текст")

    return {"text": msg.text, "custom_emoji_id": custom_emoji_id}

import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ExtBot

_TUNNEL_FILE = Path("/shared/tunnel_url")


def _get_direct_url() -> str | None:
    # Prefer the live tunnel URL written by the localhost.run sidecar — picks up
    # rotations without a bot restart. Fall back to the env var that was snapshotted
    # at startup (or set explicitly for prod).
    if _TUNNEL_FILE.exists():
        try:
            url = _TUNNEL_FILE.read_text().strip()
            if url.startswith("https://"):
                return url
        except OSError:
            pass
    url = os.environ.get("WEB_APP_URL")
    if url and url.startswith("https://"):
        return url
    return None


def get_webapp_deep_link(bot: ExtBot, chat_id: int | str | None = None) -> str | None:
    bot_username = bot.username
    if bot_username:
        app_name = os.environ.get("WEB_APP_SHORT_NAME", "dvoretskiy_webapp")
        link = f"https://t.me/{bot_username}/{app_name}"
        if chat_id is not None:
            link += f"?startapp={chat_id}"
        return link
    return _get_direct_url()


def get_bill_deep_link(bot: ExtBot, bill_id: int) -> str | None:
    """Deep link that opens the mini-app straight on a bill's distribution board.

    Encoded as `startapp=bill_<id>` (read in the web app via
    `WebApp.initDataUnsafe.start_param`). Falls back to the bare direct URL if the
    bot username is unavailable (dev/tunnel) — without the bill anchor.
    """
    return get_webapp_deep_link(bot, chat_id=f"bill_{bill_id}")


def get_webapp_keyboard(
    bot: ExtBot,
    chat_id: int | str | None = None,
    is_private: bool = False,
) -> InlineKeyboardMarkup | None:
    direct_url = _get_direct_url()
    if direct_url and is_private:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🤡",
                web_app=WebAppInfo(url=direct_url),
            )]
        ])

    link = get_webapp_deep_link(bot, chat_id)
    if not link:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤡", url=link)]
    ])

"""/make_news — generate AI news video from a replied-to message."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.news_video.pipeline import generate_news_video
from steward.helpers.news_video.sender import send_news_video

logger = logging.getLogger(__name__)

_MIN_TEXT_LEN = 100

_STAGES = {
    "enrich": "🔍 Ищу детали в интернете",
    "script": "✍️ Пишу сценарий",
    "tts": "🎙 Озвучиваю диктора",
    "images": "🖼 Собираю слайды",
    "compose": "🎬 Монтирую",
}


class NewsVideoFeature(Feature):
    command = "make_news"
    description = "Сгенерировать новостное видео из сообщения"
    help_examples = [
        "ответом на длинное сообщение → /make_news",
    ]

    @subcommand("", description="реплай на текст ≥100 символов")
    async def make_news(self, ctx: FeatureContext):
        if ctx.message is None:
            return
        reply = ctx.message.reply_to_message
        if reply is None or not (reply.text or "").strip():
            await ctx.reply(
                "Ответь этой командой на сообщение с текстом (≥100 символов)",
                markdown=False,
            )
            return
        text = reply.text.strip()
        if len(text) < _MIN_TEXT_LEN:
            await ctx.reply(
                f"Текст коротковат ({len(text)} симв, нужно ≥{_MIN_TEXT_LEN})",
                markdown=False,
            )
            return

        try:
            check_limit("make_news_user", 3, 30 * Duration.MINUTE, name=str(ctx.user_id))
            check_limit("make_news_global", 10, 30 * Duration.MINUTE)
        except Exception:
            await ctx.reply("Слишком часто. Лимит 3 за 30 минут на пользователя.", markdown=False)
            return

        placeholder = await ctx.reply("📰 Стартую…", markdown=False)

        async def progress(stage: str) -> None:
            label = _STAGES.get(stage, stage)
            if placeholder is None:
                return
            try:
                await placeholder.edit_text(f"📰 {label}…")
            except Exception:
                pass

        try:
            with tempfile.TemporaryDirectory(prefix="news_video_") as td:
                video = await generate_news_video(
                    user_id=ctx.user_id,
                    source_text=text,
                    out_dir=Path(td),
                    progress=progress,
                )
                if video is None or not video.exists():
                    if placeholder is not None:
                        try:
                            await placeholder.edit_text("❌ Не получилось — что-то пошло не так")
                        except Exception:
                            pass
                    return
                await send_news_video(ctx.message, video)
                if placeholder is not None:
                    try:
                        await placeholder.delete()
                    except Exception:
                        pass
        except Exception:
            logger.exception("/make_news failed")
            if placeholder is not None:
                try:
                    await placeholder.edit_text("❌ Ошибка при генерации (см. логи)")
                except Exception:
                    pass

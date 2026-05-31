"""/tts <voice_id> <text> — admin-only TTS playground for picking ElevenLabs voices."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.news_video.sender import send_voice_reply
from steward.helpers.news_video.tts import list_eleven_voices, synthesize_eleven_test

logger = logging.getLogger(__name__)


class TtsTestFeature(Feature):
    command = "tts"
    description = "Тест ElevenLabs голоса по voice_id (admin)"
    excluded_from_ai_router = True
    help_examples = [
        "/tts list",
        "/tts 21m00Tcm4TlvDq8ikWAM Привет, это тест голоса",
    ]

    @subcommand("list", description="Список доступных голосов", admin=True)
    async def list_voices(self, ctx: FeatureContext):
        voices = await list_eleven_voices()
        if voices is None:
            await ctx.reply("❌ Не получилось — проверь ELEVENLABS_API_KEY / EVELEN_LABS_STT")
            return
        if not voices:
            await ctx.reply("Список пуст — ни одного голоса в кабинете")
            return
        lines = ["Доступные голоса ElevenLabs:\n"]
        for v in voices[:40]:
            name = v["name"] or "?"
            extras = " ".join(filter(None, [v["gender"], v["age"], v["category"]]))
            tail = f" — {extras}" if extras else ""
            lines.append(f"`{v['voice_id']}` — *{name}*{tail}")
        await ctx.reply("\n".join(lines), markdown=True)

    @subcommand(
        "<voice_id:str> <text:rest>",
        description="<voice_id> <текст>",
        admin=True,
    )
    async def synth(self, ctx: FeatureContext, voice_id: str, text: str):
        text = (text or "").strip()
        voice_id = (voice_id or "").strip()
        if not text or not voice_id:
            await ctx.reply("Формат: /tts <voice_id> <текст>", markdown=False)
            return
        try:
            check_limit("tts_test_user", 10, Duration.MINUTE, name=str(ctx.user_id))
        except Exception:
            await ctx.reply("Лимит 10 синтезов в минуту", markdown=False)
            return

        placeholder = await ctx.reply(
            f"🔊 Синтез голосом `{voice_id[:8]}…`",
            markdown=True,
        )
        try:
            with tempfile.TemporaryDirectory(prefix="tts_test_") as td:
                out = Path(td) / "test.ogg"
                audio = await synthesize_eleven_test(text, voice_id, out)
                if audio is None or not audio.exists():
                    if placeholder is not None:
                        try:
                            await placeholder.edit_text(
                                "❌ Не получилось. Проверь:\n"
                                "• ELEVENLABS_API_KEY / EVELEN_LABS_STT настроен\n"
                                "• voice_id валидный (для free-тарифа — только дефолтные голоса)\n"
                                "• текст не пустой"
                            )
                        except Exception:
                            pass
                    return
                if ctx.message is not None:
                    await send_voice_reply(ctx.message, audio)
                if placeholder is not None:
                    try:
                        await placeholder.delete()
                    except Exception:
                        pass
        except Exception:
            logger.exception("/tts failed")
            if placeholder is not None:
                try:
                    await placeholder.edit_text("❌ Ошибка синтеза (см. логи)")
                except Exception:
                    pass

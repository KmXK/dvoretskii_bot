import logging
import tempfile
from pathlib import Path

from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.media import fetch_tg_file_to, run_ffmpeg

logger = logging.getLogger(__name__)

_RATE_LIMIT = "SHAZAM_REQUESTS"


def _format_track(track: dict) -> str:
    title = track.get("title", "?")
    artist = track.get("subtitle", "?")
    shazam_url = track.get("url", "")

    lines = [f"🎵 <b>{title}</b> — {artist}"]

    hub = track.get("hub", {})
    providers = hub.get("providers", [])
    links = []
    for provider in providers:
        caption = provider.get("caption", "")
        actions = provider.get("actions", [])
        uri = next((a.get("uri", "") for a in actions if a.get("uri")), "")
        if uri and caption:
            links.append(f'<a href="{uri}">{caption}</a>')
    if links:
        lines.append(" | ".join(links))
    elif shazam_url:
        lines.append(f'<a href="{shazam_url}">Shazam</a>')

    return "\n".join(lines)


def _file_id_from_message(message) -> str | None:
    if message is None:
        return None
    if message.voice:
        return message.voice.file_id
    if message.audio:
        return message.audio.file_id
    if message.video_note:
        return message.video_note.file_id
    return None


class ShazamFeature(Feature):
    command = "shazam"
    description = "Распознать песню по аудио или найти по тексту"
    help_examples = [
        "/shazam ответом на голосовое — распознать песню из аудио",
        "/shazam название или исполнитель — поиск по тексту",
    ]

    @subcommand(r"(?P<query>.+)", description="<текст> — поиск по названию/исполнителю")
    async def search_cmd(self, ctx: FeatureContext, query: str):
        check_limit(_RATE_LIMIT, 10, Duration.MINUTE)
        placeholder = await ctx.reply("Ищу…", markdown=False)
        try:
            from shazamio import Shazam
            result = await Shazam().search_track(query, limit=5)
            hits = result.get("tracks", {}).get("hits", [])
            if not hits:
                await placeholder.edit_text("Ничего не нашёл 🤷")
                return
            lines = []
            for i, hit in enumerate(hits[:5], 1):
                track = hit.get("track", {})
                lines.append(
                    f"{i}. <b>{track.get('title', '?')}</b> — {track.get('subtitle', '?')}"
                )
            await placeholder.edit_text("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            logger.exception("shazam text search failed: %s", e)
            await placeholder.edit_text("Не удалось выполнить поиск")

    @subcommand("", description="Распознать песню (ответом на голосовое/аудио)")
    async def recognize_cmd(self, ctx: FeatureContext):
        message = ctx.message
        if message is None:
            return

        file_id = _file_id_from_message(message.reply_to_message)
        if not file_id:
            await ctx.reply(
                "Ответь этой командой на голосовое или аудиосообщение, "
                "либо напиши /shazam название",
                markdown=False,
            )
            return

        check_limit(_RATE_LIMIT, 10, Duration.MINUTE)
        placeholder = await ctx.reply("Слушаю…", markdown=False)
        try:
            track = await self._recognize(ctx, file_id)
            if not track:
                await placeholder.edit_text("Не удалось распознать песню 🤷")
                return
            await placeholder.edit_text(_format_track(track), parse_mode="HTML")
        except Exception as e:
            logger.exception("shazam audio recognition failed: %s", e)
            await placeholder.edit_text("Не удалось распознать песню")

    async def _recognize(self, ctx: FeatureContext, file_id: str) -> dict | None:
        from shazamio import Shazam
        with tempfile.TemporaryDirectory(prefix="shazam_") as tmp_dir:
            raw_path = Path(tmp_dir) / "input"
            mp3_path = Path(tmp_dir) / "audio.mp3"
            await fetch_tg_file_to(ctx.bot, file_id, raw_path)
            await run_ffmpeg("-i", str(raw_path), "-ac", "1", "-ar", "44100", str(mp3_path))
            result = await Shazam().recognize(str(mp3_path))
            return result.get("track")

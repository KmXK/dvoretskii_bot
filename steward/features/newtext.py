import base64
import logging
import os

import httpx

from steward.framework import Feature, FeatureContext, ask_message, subcommand, wizard
from steward.helpers.media import fetch_tg_file_bytes
from steward.helpers.tg_update_helpers import get_message, split_long_message

logger = logging.getLogger(__name__)

_YANDEX_OCR_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"


def _extract_text(data: dict) -> str:
    result = data.get("result") or data
    text_ann = result.get("textAnnotation")
    if not text_ann:
        return ""
    full = text_ann.get("fullText")
    if full:
        return full.strip()
    blocks = text_ann.get("blocks") or []
    parts: list[str] = []
    for block in blocks:
        for line in block.get("lines") or []:
            for word in line.get("words") or []:
                if isinstance(word, dict) and "text" in word:
                    parts.append(word["text"])
                elif isinstance(word, str):
                    parts.append(word)
            if parts and parts[-1] and not parts[-1].endswith(" "):
                parts.append(" ")
    return "".join(parts).strip() if parts else ""


async def _yandex_ocr(content_b64: str, mime: str, api_key: str, folder_id: str) -> str:
    payload = {
        "mimeType": mime,
        "languageCodes": ["ru", "en"],
        "model": "page",
        "content": content_b64,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {api_key}",
        "x-folder-id": folder_id,
        "x-data-logging-enabled": "true",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(_YANDEX_OCR_URL, headers=headers, json=payload)
        r.raise_for_status()
        return _extract_text(r.json())


class NewTextFeature(Feature):
    command = "newtext"
    description = "Распознать текст с картинки (Yandex OCR)"

    @subcommand("", description="Запустить распознавание")
    async def start(self, ctx: FeatureContext):
        await self.start_wizard("newtext:run", ctx)

    @wizard(
        "newtext:run",
        ask_message(
            "photo",
            "Отправьте картинку",
            filter=lambda m: bool(m.photo),
            error="Отправьте картинку (фото)",
            transform=lambda m: m.photo[-1],
        ),
    )
    async def on_done(self, ctx: FeatureContext, photo):
        message = get_message(ctx.update)
        api_key = os.environ.get("AI_VISION_SECRET")
        folder_id = os.environ.get("YC_FOLDER_ID")
        if not api_key or not folder_id:
            await message.chat.send_message(
                "Yandex OCR не настроен: задайте AI_VISION_SECRET и YC_FOLDER_ID"
            )
            return
        try:
            data = await fetch_tg_file_bytes(self.bot, photo.file_id)
            content_b64 = base64.standard_b64encode(data).decode("ascii")
            mime = "JPEG"
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "PNG"
            text = await _yandex_ocr(content_b64, mime, api_key, folder_id)
        except httpx.HTTPStatusError as e:
            logger.exception("Yandex OCR HTTP error: %s", e)
            await message.chat.send_message(f"Ошибка API: {e.response.status_code}")
            return
        except Exception as e:
            logger.exception("Yandex OCR failed: %s", e)
            await message.chat.send_message(f"Не удалось распознать текст: {e}")
            return

        if not text:
            await message.chat.send_message("Текст на картинке не найден")
        else:
            for chunk in split_long_message(text):
                await message.chat.send_message(chunk)

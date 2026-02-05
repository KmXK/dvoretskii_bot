import base64
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from steward.helpers.command_validation import validate_command_msg
from steward.helpers.tg_update_helpers import get_message, split_long_message
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step

logger = logging.getLogger(__name__)

YANDEX_OCR_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"


def _extract_file_path(file_path: str) -> str:
    if file_path.startswith("http://") or file_path.startswith("https://"):
        parsed_url = urlparse(file_path)
        path = parsed_url.path
        if path.startswith("/file/bot"):
            file_path = path[len("/file/bot") :]
            first_slash_idx = file_path.find("/")
            if first_slash_idx > 0:
                file_path = file_path[first_slash_idx + 1 :]
        else:
            file_path = path.lstrip("/")
    return file_path


async def _read_photo_bytes(context, file_id: str) -> bytes:
    tg_file = await context.bot.get_file(file_id)
    if tg_file.file_path:
        rel = _extract_file_path(tg_file.file_path)
        local_path = Path(f"/data/{context.bot.token}/{rel}")
        if local_path.exists():
            return local_path.read_bytes()
    return bytes(await tg_file.download_as_bytearray())


def _extract_text_from_yandex_response(data: dict) -> str:
    result = data.get("result") or data
    text_ann = result.get("textAnnotation")
    if not text_ann:
        return ""
    full = text_ann.get("fullText")
    if full:
        return full.strip()
    blocks = text_ann.get("blocks") or []
    parts = []
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


async def _yandex_ocr(
    content_b64: str, mime_type: str, api_key: str, folder_id: str
) -> str:
    payload = {
        "mimeType": mime_type,
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
        r = await client.post(YANDEX_OCR_URL, headers=headers, json=payload)
        r.raise_for_status()
        return _extract_text_from_yandex_response(r.json())


class CollectImageStepYandex(Step):
    def __init__(self, name: str):
        self.name = name
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            await context.message.reply_text("Отправьте картинку")
            self.is_waiting = True
            return False

        if not context.message.photo:
            await context.message.reply_text("Отправьте картинку (фото)")
            return False

        api_key = os.environ.get("AI_VISION_SECRET")
        folder_id = os.environ.get("YC_FOLDER_ID")
        if not api_key or not folder_id:
            await context.message.reply_text(
                "Yandex OCR не настроен: задайте AI_VISION_SECRET и YC_FOLDER_ID"
            )
            self.is_waiting = False
            return True

        photo = context.message.photo[-1]
        try:
            data = await _read_photo_bytes(context, photo.file_id)
            content_b64 = base64.standard_b64encode(data).decode("ascii")
            mime = "JPEG"
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "PNG"
            text = await _yandex_ocr(content_b64, mime, api_key, folder_id)
        except httpx.HTTPStatusError as e:
            logger.exception("Yandex OCR HTTP error: %s", e)
            await context.message.reply_text(f"Ошибка API: {e.response.status_code}")
            self.is_waiting = False
            return True
        except Exception as e:
            logger.exception("Yandex OCR failed: %s", e)
            await context.message.reply_text(f"Не удалось распознать текст: {e}")
            self.is_waiting = False
            return True

        self.is_waiting = False
        if not text:
            await context.message.reply_text("Текст на картинке не найден")
        else:
            for chunk in split_long_message(text):
                await context.message.reply_text(chunk)
        return True

    async def callback(self, context):
        return False

    def stop(self):
        self.is_waiting = False


class NewTextHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__([CollectImageStepYandex("image")])

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "newtext"):
            return False
        return update.message is not None and bool(update.message.text)

    async def on_session_finished(self, update, session_context):
        pass

    async def on_stop(self, update, session_context):
        await get_message(update).chat.send_message("Отменено")

    def help(self):
        return "/newtext — распознать текст с картинки (Yandex OCR)"

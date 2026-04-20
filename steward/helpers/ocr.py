import logging
import os

from steward.helpers.ai import make_nvidia_vlm_describe, nvidia_is_configured

logger = logging.getLogger(__name__)

_OCR_PROMPT = (
    "Извлеки ВЕСЬ текст с изображения. Сохрани порядок и расположение "
    "(столбцы, строки, таблицы — по строкам, позиции разделяй табами или пробелами). "
    "Без комментариев, без форматирования markdown, без кавычек. "
    "Если текста нет — верни пустую строку."
)


async def extract_text_from_image(content_b64: str, mime: str) -> str:
    if nvidia_is_configured():
        try:
            text = await make_nvidia_vlm_describe(0, _OCR_PROMPT, [content_b64], max_tokens=2000)
            if text and text.strip():
                return text.strip()
        except Exception as e:
            logger.warning("NVIDIA OCR failed, falling back to Yandex: %s", e)

    api_key = os.environ.get("AI_VISION_SECRET")
    folder_id = os.environ.get("YC_FOLDER_ID")
    if not api_key or not folder_id:
        return ""

    try:
        from steward.features.newtext import _yandex_ocr
        return await _yandex_ocr(content_b64, mime, api_key, folder_id)
    except Exception as e:
        logger.exception("Yandex OCR failed: %s", e)
        return ""

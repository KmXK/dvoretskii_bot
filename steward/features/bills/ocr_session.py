import base64
import logging

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.features.bills.ocr import (
    build_bill_ai_input,
    build_new_people_rows,
    parse_ai_bill_response,
    read_voice_bytes,
    transcribe_voice_bytes,
)
from steward.features.bills.sheets import (
    BILL_DATA_SHEET_NAME,
    BILL_DATA_SHEET_NAME_FALLBACK,
    BILL_MAIN_SHEET_NAME,
    parse_known_places,
    parse_people_places,
    read_bill_people_places_rows,
)
from steward.helpers.media import fetch_tg_file_bytes
from steward.helpers.ai import BILL_OCR_PROMPT, make_yandex_ai_query
from steward.helpers.ocr import extract_text_from_image
from steward.helpers.google_drive import insert_rows_into_sheet
from steward.helpers.tg_update_helpers import get_message
from steward.session.step import Step

logger = logging.getLogger(__name__)


def build_bill_context_start_keyboard(cb_start, cb_no, file_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🧾 Добавить контекст",
                callback_data=cb_start(file_id=file_id),
            ),
            InlineKeyboardButton("Нет", callback_data=cb_no()),
        ]
    ])


def build_bill_context_stop_keyboard(cb_stop, file_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⏹ Стоп",
                callback_data=cb_stop(file_id=file_id),
            )
        ]
    ])


class CollectBillContextStep(Step):
    def __init__(self, cb_stop):
        self._cb_stop = cb_stop
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            context.session_context.setdefault("bill_context_parts", [])
            file_id = context.session_context.get("file_id", "")
            await context.message.reply_text(
                "Отправляйте контекст для счёта:\n"
                "• фото — распознаю текст с картинки\n"
                "• голосовые — расшифрую в текст\n\n"
                "Когда закончите, нажмите кнопку «Стоп».",
                reply_markup=build_bill_context_stop_keyboard(self._cb_stop, file_id),
            )
            self.is_waiting = True
            return False

        text_parts: list[str] = context.session_context.setdefault("bill_context_parts", [])

        if context.message.photo:
            photo = context.message.photo[-1]
            try:
                data = await fetch_tg_file_bytes(context.bot, photo.file_id)
                content_b64 = base64.standard_b64encode(data).decode("ascii")
                mime = "JPEG"
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    mime = "PNG"
                text = await extract_text_from_image(content_b64, mime)
            except httpx.HTTPStatusError as e:
                logger.exception("OCR HTTP error: %s", e)
                await context.message.reply_text(
                    f"Ошибка OCR API: {e.response.status_code}"
                )
                return False
            except Exception as e:
                logger.exception("OCR failed: %s", e)
                await context.message.reply_text(f"Не удалось распознать фото: {e}")
                return False

            if not text:
                await context.message.reply_text("Текст на картинке не найден")
                return False

            text_parts.append(f"[Фото]\n{text}")
            await context.message.reply_text("✅ Фото добавлено в контекст")
            return False

        if context.message.voice:
            try:
                voice_bytes = await read_voice_bytes(context, context.message.voice.file_id)
                voice_text = await transcribe_voice_bytes(voice_bytes)
            except Exception as e:
                logger.exception("Voice transcription failed: %s", e)
                await context.message.reply_text(f"Не удалось обработать голосовое: {e}")
                return False

            if not voice_text:
                await context.message.reply_text(
                    "Не удалось расшифровать голосовое. Проверьте EVELEN_LABS_STT."
                )
                return False

            text_parts.append(f"[Голосовое]\n{voice_text}")
            await context.message.reply_text("✅ Голосовое добавлено в контекст")
            return False

        if (
            context.message.text
            and context.message.text.strip()
            and not context.message.text.startswith("/")
        ):
            text_parts.append(f"[Текст]\n{context.message.text.strip()}")
            await context.message.reply_text("✅ Текст добавлен в контекст")
            return False

        await context.message.reply_text(
            "Поддерживаются фото, голосовые и текст. "
            "Когда закончите — нажмите кнопку «Стоп»."
        )
        return False

    async def callback(self, context):
        if not self.is_waiting:
            await context.callback_query.message.edit_reply_markup(reply_markup=None)
            await context.callback_query.answer()
            context.session_context.setdefault("bill_context_parts", [])
            file_id = context.session_context.get("file_id", "")
            await context.callback_query.message.chat.send_message(
                "Отправляйте контекст для счёта:\n"
                "• фото — распознаю текст с картинки\n"
                "• голосовые — расшифрую в текст\n\n"
                "Когда закончите, нажмите кнопку «Стоп».",
                reply_markup=build_bill_context_stop_keyboard(self._cb_stop, file_id),
            )
            self.is_waiting = True
            return False

        data = context.callback_query.data or ""
        expected = self._cb_stop(file_id=context.session_context.get("file_id", ""))
        if data != expected:
            return False
        await context.callback_query.answer()
        try:
            await context.callback_query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("Could not clear stop keyboard", exc_info=True)
        self.is_waiting = False
        return True

    def stop(self):
        self.is_waiting = False


async def finalize_ocr(
    repository_unused,
    update,
    session_context: dict,
):
    text_parts: list[str] = session_context.get("bill_context_parts", [])
    ocr_text = "\n\n".join(text_parts).strip()
    file_id = session_context.get("file_id")
    msg = get_message(update)

    if not ocr_text:
        await msg.chat.send_message("Контекст пуст. Нечего добавлять в счёт.")
        return
    if len(ocr_text) > 15000:
        ocr_text = ocr_text[:15000]
        await msg.chat.send_message(
            "Контекст был слишком длинным, отправил в нейронку первые 15000 символов."
        )
    if not file_id:
        await msg.chat.send_message("Не найден файл счёта")
        return

    people_places_rows = read_bill_people_places_rows(file_id)
    people_places = parse_people_places(people_places_rows)
    known_places = parse_known_places(people_places_rows)
    ai_input = build_bill_ai_input(ocr_text, people_places, known_places)

    try:
        ai_response = await make_yandex_ai_query(
            msg.chat.id,
            [("user", ai_input)],
            BILL_OCR_PROMPT,
        )
    except Exception as e:
        logger.exception("AI request failed: %s", e)
        await msg.chat.send_message(f"Ошибка AI: {e}")
        return

    rows, ai_data_rows = parse_ai_bill_response(ai_response)
    if not rows:
        await msg.chat.send_message(
            f"Не удалось разобрать ответ AI:\n{ai_response}"
        )
        return

    if not insert_rows_into_sheet(file_id, rows, BILL_MAIN_SHEET_NAME):
        await msg.chat.send_message("Не удалось записать данные в таблицу")
        return

    new_people_rows = build_new_people_rows(people_places, ai_data_rows)
    data_inserted = 0
    if new_people_rows:
        if insert_rows_into_sheet(file_id, new_people_rows, BILL_DATA_SHEET_NAME) or insert_rows_into_sheet(
            file_id,
            new_people_rows,
            BILL_DATA_SHEET_NAME_FALLBACK,
        ):
            data_inserted = len(new_people_rows)
        else:
            await msg.chat.send_message(
                "⚠️ Расходы добавлены, но не удалось обновить лист 'данные'."
            )

    lines = [f"✅ Добавлено {len(rows)} строк в счёт:"]
    for r in rows:
        lines.append(f"• {r[0]} — {r[1]}")
    if data_inserted > 0:
        lines.append("")
        lines.append(f"🧩 Добавлено {data_inserted} новых участников в лист 'данные'")
    await msg.chat.send_message("\n".join(lines))

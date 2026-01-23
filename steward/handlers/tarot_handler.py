import asyncio
import json
import logging
import os
import random
import tempfile
from pathlib import Path

from telegram import InputFile

from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.ai import TAROT_PROMPT, AIModels, make_ai_query_ext

logger = logging.getLogger(__name__)

TAROT_JSON_PATH = Path("data/tarot/tarot-images.json")
TAROT_CARDS_PATH = Path("data/tarot/cards")
TAROT_TABLE_PATH = Path("data/tarot/table.png")


def load_tarot_cards():
    with open(TAROT_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("cards", [])


async def _run_ffmpeg(*args: str):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"ffmpeg failed: {stderr.decode()}")


async def _create_tarot_table(
    card_paths: list[Path], table_path: Path, output_path: str
):
    TABLE_WIDTH = 1280
    TABLE_HEIGHT = 692
    ORIGINAL_CARD_WIDTH = 350
    ORIGINAL_CARD_HEIGHT = 600

    CARD_SCALE = 0.4
    BOTTOM_SPACING = 30
    PERSPECTIVE_DEGREES = 10
    SIDE_PERSPECTIVE_OFFSET_RATIO = 0.13
    CARD_PADDING_RATIO = 1.1
    CARD_BRIGHTNESS = -0.5
    CARD_CONTRAST = 1
    CARD_SATURATION = 1.0
    CARD_GAMMA = 1.0
    VERTICAL_OFFSET_RATIO = 0.8
    LEFT_MARGIN = 330
    CARD_SPACING = 70

    card_aspect_ratio = ORIGINAL_CARD_HEIGHT / ORIGINAL_CARD_WIDTH
    available_width = TABLE_WIDTH - (BOTTOM_SPACING * 2)
    card_width = int((available_width // 3) * CARD_SCALE)
    card_height = int(card_width * card_aspect_ratio)

    perspective_offset = int(card_width * (PERSPECTIVE_DEGREES / 90.0))
    card_padding = int(card_height * CARD_PADDING_RATIO)

    positions = []
    filter_parts = []

    for i, card_path in enumerate(card_paths):
        card_index = i + 1
        filter_parts.append(
            f"[{card_index}:v]scale={card_width}:{card_height}[card{i}_scaled]"
        )
        filter_parts.append(
            f"[card{i}_scaled]eq=brightness={CARD_BRIGHTNESS}:contrast={CARD_CONTRAST}:saturation={CARD_SATURATION}:gamma={CARD_GAMMA}[card{i}_dark]"
        )

        if i == 0:
            x = LEFT_MARGIN
            side_offset = -int(card_width * SIDE_PERSPECTIVE_OFFSET_RATIO)
        elif i == 1:
            x = LEFT_MARGIN + card_width + CARD_SPACING
            side_offset = 0
        else:
            x = LEFT_MARGIN + card_width * 2 + CARD_SPACING * 2
            side_offset = int(card_width * SIDE_PERSPECTIVE_OFFSET_RATIO)

        y = int((TABLE_HEIGHT - card_height) * VERTICAL_OFFSET_RATIO)
        positions.append((x, y))

        pad_width = card_width + perspective_offset * 2
        pad_height = card_padding
        pad_x = perspective_offset
        pad_y = (pad_height - card_height) // 2

        filter_parts.append(
            f"[card{i}_dark]pad={pad_width}:{pad_height}:{pad_x}:{pad_y}:color=0x00000000[card{i}_padded]"
        )

        top_left_x = pad_x - perspective_offset + side_offset
        top_right_x = pad_x + card_width + perspective_offset + side_offset
        bottom_left_x = pad_x
        bottom_right_x = pad_x + card_width

        filter_parts.append(
            f"[card{i}_padded]perspective="
            f"{top_left_x}:{pad_y}:"
            f"{top_right_x}:{pad_y}:"
            f"{bottom_left_x}:{pad_height - pad_y}:"
            f"{bottom_right_x}:{pad_height - pad_y}"
            f"[card{i}_perspective]"
        )

    overlay_parts = []
    current_base = "[0:v]"
    for i in range(len(card_paths)):
        overlay_parts.append(
            f"{current_base}[card{i}_perspective]overlay={positions[i][0]}:{positions[i][1]}[overlay{i}]"
        )
        current_base = f"[overlay{i}]"

    filter_complex = ";".join(filter_parts) + ";" + ";".join(overlay_parts)

    args = ["-i", str(table_path)]
    for card_path in card_paths:
        args.extend(["-i", str(card_path)])
    args.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            f"[overlay{len(card_paths) - 1}]",
            "-frames:v",
            "1",
            output_path,
        ]
    )

    await _run_ffmpeg(*args)


@CommandHandler(
    "tarot",
    only_admin=False,
    arguments_template=r"(?P<question>.+)?",
)
class TarotHandler(Handler):
    async def chat(self, context, question: str | None = None):
        if not TAROT_JSON_PATH.exists():
            logger.warning("TarotHandler skipped: %s not found", TAROT_JSON_PATH)
            return False

        if not TAROT_CARDS_PATH.exists():
            logger.warning("TarotHandler skipped: %s not found", TAROT_CARDS_PATH)
            return False

        if not TAROT_TABLE_PATH.exists():
            logger.warning("TarotHandler skipped: %s not found", TAROT_TABLE_PATH)
            return False

        try:
            if not question or not question.strip():
                question = "расскажи про мою судьбу"
            else:
                context.message.reply_text(f"Задаю вопрос: {question}")
                question = question.strip()

            cards = load_tarot_cards()

            if not cards:
                await context.message.reply_text("Не удалось загрузить карты таро")
                return True

            selected_cards = random.sample(cards, min(3, len(cards)))

            card_paths = []
            for card in selected_cards:
                img_filename = card.get("img")
                if not img_filename:
                    continue

                img_path = TAROT_CARDS_PATH / img_filename
                if not img_path.exists():
                    logger.warning(f"Изображение не найдено: {img_path}")
                    continue

                card_paths.append(img_path)

            if len(card_paths) != 3:
                await context.message.reply_text("Не удалось загрузить все три карты")
                return True

            fd, out_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)

            try:
                await _create_tarot_table(card_paths, TAROT_TABLE_PATH, out_path)

                prompt_text = f"[Вопрос]\n{question}\n\n"
                for i, card in enumerate(selected_cards):
                    card_json = json.dumps(card, ensure_ascii=False, indent=2)
                    prompt_text += f"[Карта{i + 1}]\n{card_json}\n\n"

                ai_response = await make_ai_query_ext(
                    context.message.from_user.id,
                    AIModels.YANDEXGPT_5_PRO,
                    [("user", prompt_text)],
                    TAROT_PROMPT,
                )

                with open(out_path, "rb") as f:
                    await context.message.reply_photo(
                        InputFile(f, filename="tarot_reading.png"),
                    )

                max_message_length = 4096
                if len(ai_response) <= max_message_length:
                    await context.message.reply_text(ai_response, parse_mode="Markdown")
                else:
                    offset = 0
                    while offset < len(ai_response):
                        chunk = ai_response[offset : offset + max_message_length]
                        if offset + max_message_length < len(ai_response):
                            last_newline = chunk.rfind("\n")
                            if last_newline > max_message_length - 200:
                                chunk = chunk[:last_newline]
                                offset += last_newline + 1
                            else:
                                offset += max_message_length
                        else:
                            offset = len(ai_response)
                        await context.message.reply_text(chunk, parse_mode="Markdown")
            finally:
                os.unlink(out_path)

            return True

        except Exception as e:
            logger.exception(f"Ошибка в обработчике таро: {e}")
            await context.message.reply_text(
                f"Произошла ошибка при гадании на картах таро: {e}"
            )
            return True

    def help(self):
        return "/tarot [вопрос] - гадание на трех картах таро"

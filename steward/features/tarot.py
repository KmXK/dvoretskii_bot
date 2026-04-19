import json
import logging
import os
import random
import tempfile
from pathlib import Path

from telegram import InputFile

from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.ai import TAROT_PROMPT, make_yandex_ai_query
from steward.helpers.media import run_ffmpeg

logger = logging.getLogger(__name__)

_TAROT_JSON_PATH = Path("data/tarot/tarot-images.json")
_TAROT_CARDS_PATH = Path("data/tarot/cards")
_TAROT_TABLE_PATH = Path("data/tarot/table.png")


def _load_tarot_cards() -> list[dict]:
    with open(_TAROT_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("cards", [])


async def _create_tarot_table(card_paths: list[Path], table_path: Path, output_path: str):
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
        ci = i + 1
        filter_parts.append(f"[{ci}:v]scale={card_width}:{card_height}[card{i}_scaled]")
        filter_parts.append(
            f"[card{i}_scaled]eq=brightness={CARD_BRIGHTNESS}:contrast={CARD_CONTRAST}:"
            f"saturation={CARD_SATURATION}:gamma={CARD_GAMMA}[card{i}_dark]"
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
    args.extend([
        "-filter_complex",
        filter_complex,
        "-map",
        f"[overlay{len(card_paths) - 1}]",
        "-frames:v",
        "1",
        output_path,
    ])
    await run_ffmpeg(*args)


class TarotFeature(Feature):
    command = "tarot"
    description = "Гадание на трёх картах таро"
    help_examples = [
        "«погадай на картах таро» → /tarot",
        "«таро что меня ждёт завтра» → /tarot что меня ждёт завтра",
    ]

    @subcommand("", description="Гадание без вопроса")
    async def default(self, ctx: FeatureContext):
        await self._divine(ctx, "расскажи про мою судьбу", show_question=False)

    @subcommand("<question:rest>", description="Гадание с вопросом")
    async def with_question(self, ctx: FeatureContext, question: str):
        await self._divine(ctx, question.strip(), show_question=True)

    async def _divine(self, ctx: FeatureContext, question: str, show_question: bool):
        if not _TAROT_JSON_PATH.exists() or not _TAROT_CARDS_PATH.exists() or not _TAROT_TABLE_PATH.exists():
            logger.warning("Tarot assets missing")
            return False
        if show_question and ctx.message:
            await ctx.message.reply_text(f"Задаю вопрос: {question}")
        try:
            cards = _load_tarot_cards()
            if not cards:
                await ctx.reply("Не удалось загрузить карты таро")
                return
            selected = random.sample(cards, min(3, len(cards)))
            card_paths: list[Path] = []
            for card in selected:
                img = card.get("img")
                if not img:
                    continue
                p = _TAROT_CARDS_PATH / img
                if not p.exists():
                    logger.warning("card image not found: %s", p)
                    continue
                card_paths.append(p)
            if len(card_paths) != 3:
                await ctx.reply("Не удалось загрузить все три карты")
                return
            fd, out_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                await _create_tarot_table(card_paths, _TAROT_TABLE_PATH, out_path)
                prompt_text = f"[Вопрос]\n{question}\n\n"
                for i, card in enumerate(selected):
                    prompt_text += f"[Карта{i + 1}]\n{json.dumps(card, ensure_ascii=False, indent=2)}\n\n"
                ai_response = await make_yandex_ai_query(
                    ctx.user_id,
                    [("user", prompt_text)],
                    TAROT_PROMPT,
                )
                with open(out_path, "rb") as f:
                    if ctx.message:
                        await ctx.message.reply_photo(
                            InputFile(f, filename="tarot_reading.png"),
                        )
                max_len = 4096
                if len(ai_response) <= max_len:
                    await ctx.reply(ai_response)
                else:
                    offset = 0
                    while offset < len(ai_response):
                        chunk = ai_response[offset : offset + max_len]
                        if offset + max_len < len(ai_response):
                            last_nl = chunk.rfind("\n")
                            if last_nl > max_len - 200:
                                chunk = chunk[:last_nl]
                                offset += last_nl + 1
                            else:
                                offset += max_len
                        else:
                            offset = len(ai_response)
                        await ctx.reply(chunk)
            finally:
                os.unlink(out_path)
        except Exception as e:
            logger.exception("Tarot failed: %s", e)
            await ctx.reply(f"Произошла ошибка при гадании на картах таро: {e}")

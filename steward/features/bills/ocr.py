import asyncio
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from steward.features.bills.amounts import normalize_name, parse_amount
from steward.helpers.stt import transcribe_audio_bytes

logger = logging.getLogger(__name__)


async def run_ffmpeg(*args: str):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"ffmpeg failed: {stderr.decode(errors='replace')}")


async def read_voice_bytes(context, file_id: str) -> bytes:
    tg_file = await context.bot.get_file(file_id)
    try:
        return bytes(await tg_file.download_as_bytearray())
    except Exception:
        file_path = tg_file.file_path
        if not file_path:
            raise
        if file_path.startswith("http://") or file_path.startswith("https://"):
            parsed = urlparse(file_path)
            path = parsed.path
            if path.startswith("/file/bot"):
                rel = path[len("/file/bot") :]
                first_slash = rel.find("/")
                file_path = rel[first_slash + 1 :] if first_slash > 0 else rel.lstrip("/")
            else:
                file_path = path.lstrip("/")
        local_path = Path(f"/data/{context.bot.token}/{file_path}")
        if not local_path.exists():
            raise
        return local_path.read_bytes()


async def transcribe_voice_bytes(data: bytes) -> str | None:
    with tempfile.TemporaryDirectory(prefix="bill_voice_stt_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_audio = tmp_path / "voice.ogg"
        prepared_audio = tmp_path / "voice.mp3"
        source_audio.write_bytes(data)
        await run_ffmpeg(
            "-i", str(source_audio),
            "-ac", "1",
            "-ar", "44100",
            str(prepared_audio),
        )
        return await transcribe_audio_bytes(
            prepared_audio.read_bytes(),
            with_speaker_labels=False,
        )


def build_people_places_prompt_block(
    people_places: dict[str, str], known_places: list[str]
) -> str:
    lines: list[str] = []
    lines.append("известные действующие лица:")
    if not people_places:
        lines.append("(пока пусто)")
    else:
        for person, place in sorted(
            people_places.items(), key=lambda x: normalize_name(x[0])
        ):
            lines.append(f"- {person}" + (f" | {place}" if place else ""))
    lines.append("")
    lines.append("известные места:")
    if not known_places:
        lines.append("(пока пусто)")
    else:
        for place in known_places:
            lines.append(f"- {place}")
    return "\n".join(lines)


def build_bill_ai_input(
    context_text: str, people_places: dict[str, str], known_places: list[str]
) -> str:
    return (
        "КОНТЕКСТ ДЛЯ РАЗБОРА:\n"
        f"{context_text}\n\n"
        "СПРАВОЧНИК ИЗ ЛИСТА 'Данные':\n"
        f"{build_people_places_prompt_block(people_places, known_places)}"
    )


def parse_ai_bill_response(text: str) -> tuple[list[list[str]], list[list[str]]]:
    main_rows: list[list[str]] = []
    data_rows: list[list[str]] = []
    section: str | None = None

    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = line.strip("[]").strip().lower().rstrip(":")
        if normalized == "общее":
            section = "main"
            continue
        if normalized == "данные":
            section = "data"
            continue

        if "|" not in line or section is None:
            continue

        parts = [p.strip() for p in line.split("|")]
        if section == "main":
            if len(parts) < 5:
                continue
            if normalize_name(parts[0]) == "наименование":
                continue
            name = parts[0]
            amount_raw = parts[1]
            payers = parts[2]
            factual_payer = parts[3]
            source = parts[4]
            if not name or not payers or not factual_payer:
                continue
            try:
                amount = parse_amount(amount_raw)
            except ValueError:
                continue
            amount_str = f"{amount:.2f}".replace(".", ",")
            main_rows.append([name, amount_str, payers, factual_payer, source])
            continue

        if section == "data":
            if len(parts) < 2:
                continue
            person = parts[0]
            place = parts[1]
            if not person or normalize_name(person) == "персонаж":
                continue
            data_rows.append([person, place])

    return main_rows, data_rows


def build_new_people_rows(
    existing_people_places: dict[str, str], ai_data_rows: list[list[str]]
) -> list[list[str]]:
    synthetic_aliases = {
        "ратибор",
        "ротибор",
        "ярополк",
        "добрыня",
        "мстислав",
        "святозар",
        "велимир",
        "борислав",
        "мирослав",
        "всеволод",
        "ростислав",
    }
    existing_names = {normalize_name(name) for name in existing_people_places}
    seen_new: set[str] = set()
    out: list[list[str]] = []
    for row in ai_data_rows:
        person = (row[0] if len(row) > 0 else "").strip()
        place = (row[1] if len(row) > 1 else "").strip()
        norm = normalize_name(person)
        if not norm or norm in existing_names or norm in seen_new:
            continue
        if any(norm.startswith(alias) for alias in synthetic_aliases):
            continue
        out.append([person, place])
        seen_new.add(norm)
    return out

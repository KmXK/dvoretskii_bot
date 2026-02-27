from typing import Any

OLD_RUSSIAN_NAMES = (
    "Ратибор",
    "Ярополк",
    "Добрыня",
    "Мстислав",
    "Святозар",
    "Велимир",
    "Борислав",
    "Мирослав",
    "Всеволод",
    "Ростислав",
)

_PUNCT_NO_SPACE_BEFORE = {".", ",", "!", "?", ":", ";", ")"}


def _join_chunks(chunks: list[str]) -> str:
    parts: list[str] = []
    for raw_chunk in chunks:
        chunk = (raw_chunk or "").strip()
        if not chunk:
            continue
        if parts and (chunk[:1] in _PUNCT_NO_SPACE_BEFORE or parts[-1].endswith("(")):
            parts[-1] += chunk
        else:
            parts.append(chunk)
    return " ".join(parts).strip()


def build_named_speakers_text(words: list[Any]) -> str:
    speaker_aliases: dict[str, str] = {}
    lines: list[str] = []
    current_speaker: str | None = None
    current_chunks: list[str] = []
    next_alias_idx = 0

    for part in words:
        chunk = (getattr(part, "text", "") or "").strip()
        if not chunk:
            continue

        speaker_id = str(getattr(part, "speaker_id", "") or "speaker_1")
        if speaker_id not in speaker_aliases:
            base_name = OLD_RUSSIAN_NAMES[next_alias_idx % len(OLD_RUSSIAN_NAMES)]
            round_idx = next_alias_idx // len(OLD_RUSSIAN_NAMES)
            speaker_aliases[speaker_id] = (
                base_name if round_idx == 0 else f"{base_name} {round_idx + 1}"
            )
            next_alias_idx += 1

        speaker_name = speaker_aliases[speaker_id]

        if current_speaker is None:
            current_speaker = speaker_name
            current_chunks = [chunk]
            continue

        if speaker_name != current_speaker:
            phrase = _join_chunks(current_chunks)
            if phrase:
                lines.append(f"{current_speaker}: {phrase}")
            current_speaker = speaker_name
            current_chunks = [chunk]
        else:
            current_chunks.append(chunk)

    if current_speaker is not None:
        phrase = _join_chunks(current_chunks)
        if phrase:
            lines.append(f"{current_speaker}: {phrase}")

    return "\n".join(lines).strip()

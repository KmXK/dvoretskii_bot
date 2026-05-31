from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from steward.data.models.curse import CurseParticipant, CursePunishment
from steward.features.transcribe import TranscribeFeature
from steward.framework.types import from_chat_context
from tests.conftest import DEFAULT_USER_ID, make_repository, make_text_context


def _make_feature(repo):
    feature = TranscribeFeature()
    feature.repository = repo
    feature.bot = MagicMock()
    return feature


def _prepare_repo():
    repo = make_repository()
    repo.db.curse_words = {"мат"}
    repo.db.curse_punishments = [CursePunishment(id=1, coeff=4, title="приседаний")]
    repo.db.curse_participants = [
        CurseParticipant(user_id=DEFAULT_USER_ID, subscribed_at=datetime.now(timezone.utc))
    ]
    repo.is_capability_enabled = MagicMock(return_value=True)
    return repo


async def test_transcribe_command_counts_curses_for_source_voice_author(monkeypatch):
    repo = _prepare_repo()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    source_message = ctx.message
    source_message.forward_origin = None

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=Path("/tmp/audio.ogg")))
    monkeypatch.setattr(
        "steward.features.transcribe.create_transcription_reply",
        AsyncMock(return_value="мат мат"),
    )

    await feature._transcribe(
        ctx,
        file_id="file-id",
        is_video_note=False,
        source_message=source_message,
    )

    ctx.metrics.inc.assert_called_once_with(
        "bot_curse_words_total",
        {"user_id": str(DEFAULT_USER_ID), "user_name": "testuser"},
        value=2,
    )
    source_message.set_reaction.assert_called_once_with("🤬")
    assert len(repo.db.curse_punishment_debts) == 1
    assert repo.db.curse_punishment_debts[0].user_id == DEFAULT_USER_ID
    assert repo.db.curse_punishment_debts[0].punishment_count == 8
    repo.is_capability_enabled.assert_called_once()


async def test_transcribe_command_ignores_forwarded_voice(monkeypatch):
    repo = _prepare_repo()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    source_message = ctx.message
    source_message.forward_origin = object()

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=Path("/tmp/audio.ogg")))
    monkeypatch.setattr(
        "steward.features.transcribe.create_transcription_reply",
        AsyncMock(return_value="мат мат"),
    )

    await feature._transcribe(
        ctx,
        file_id="file-id",
        is_video_note=False,
        source_message=source_message,
    )

    ctx.metrics.inc.assert_not_called()
    source_message.set_reaction.assert_not_called()
    assert repo.db.curse_punishment_debts == []


async def test_transcribe_command_ignores_external_reply_without_source_author(monkeypatch):
    repo = _prepare_repo()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    reply_target = ctx.message
    reply_target.forward_origin = None

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=Path("/tmp/audio.ogg")))
    monkeypatch.setattr(
        "steward.features.transcribe.create_transcription_reply",
        AsyncMock(return_value="мат мат"),
    )

    await feature._transcribe(
        ctx,
        file_id="file-id",
        is_video_note=False,
        source_message=reply_target,
        curse_source_message=None,
    )

    ctx.metrics.inc.assert_not_called()
    reply_target.set_reaction.assert_not_called()
    assert repo.db.curse_punishment_debts == []


async def test_transcribe_command_respects_disabled_curse_capability(monkeypatch):
    repo = _prepare_repo()
    repo.is_capability_enabled = MagicMock(return_value=False)
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    source_message = ctx.message
    source_message.forward_origin = None

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=Path("/tmp/audio.ogg")))
    monkeypatch.setattr(
        "steward.features.transcribe.create_transcription_reply",
        AsyncMock(return_value="мат мат"),
    )

    await feature._transcribe(
        ctx,
        file_id="file-id",
        is_video_note=False,
        source_message=source_message,
    )

    ctx.metrics.inc.assert_not_called()
    source_message.set_reaction.assert_not_called()
    assert repo.db.curse_punishment_debts == []

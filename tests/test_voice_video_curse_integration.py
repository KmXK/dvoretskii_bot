from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from steward.data.models.curse import CurseParticipant, CursePunishment
from steward.features.voice_video import VoiceVideoFeature, _PendingVoiceRequest
from steward.framework.types import from_chat_context
from tests.conftest import DEFAULT_USER_ID, make_repository, make_text_context


def _make_feature(repo):
    feature = VoiceVideoFeature()
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


def _pending():
    return _PendingVoiceRequest(
        file_id="file-id",
        requester_user_id=DEFAULT_USER_ID,
        speaker_user_id=DEFAULT_USER_ID,
        speaker_username="testuser",
        speaker_fallback_name=None,
        speaker_first_name="Test",
        duration=5,
        transcribe_clicked=True,
    )


async def test_auto_voice_transcription_counts_curses_for_voice_author(monkeypatch):
    repo = _prepare_repo()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    source_message = ctx.message
    source_message.forward_origin = None
    bot_message = MagicMock()
    bot_message.edit_text = AsyncMock()

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=Path("/tmp/audio.ogg")))
    monkeypatch.setattr("steward.features.voice_video.transcribe_voice", AsyncMock(return_value="мат мат"))
    monkeypatch.setattr(
        "steward.features.voice_video.create_transcription_reply",
        AsyncMock(return_value="мат мат"),
    )

    await feature._run_auto_transcription(ctx, "request-id", _pending(), source_message, bot_message)

    ctx.metrics.inc.assert_called_once_with(
        "bot_curse_words_total",
        {"user_id": str(DEFAULT_USER_ID), "user_name": "testuser"},
        value=2,
    )
    source_message.set_reaction.assert_called_once_with("🤬")
    assert len(repo.db.curse_punishment_debts) == 1
    assert repo.db.curse_punishment_debts[0].user_id == DEFAULT_USER_ID
    assert repo.db.curse_punishment_debts[0].punishment_count == 8


async def test_auto_voice_transcription_ignores_forwarded_voice(monkeypatch):
    repo = _prepare_repo()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    source_message = ctx.message
    source_message.forward_origin = object()
    bot_message = MagicMock()
    bot_message.edit_text = AsyncMock()

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=Path("/tmp/audio.ogg")))
    monkeypatch.setattr("steward.features.voice_video.transcribe_voice", AsyncMock(return_value="мат мат"))
    monkeypatch.setattr(
        "steward.features.voice_video.create_transcription_reply",
        AsyncMock(return_value="мат мат"),
    )

    await feature._run_auto_transcription(ctx, "request-id", _pending(), source_message, bot_message)

    ctx.metrics.inc.assert_not_called()
    source_message.set_reaction.assert_not_called()
    assert repo.db.curse_punishment_debts == []


async def test_auto_voice_transcription_respects_disabled_curse_capability(monkeypatch):
    repo = _prepare_repo()
    repo.is_capability_enabled = MagicMock(return_value=False)
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    source_message = ctx.message
    source_message.forward_origin = None
    bot_message = MagicMock()
    bot_message.edit_text = AsyncMock()

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=Path("/tmp/audio.ogg")))
    monkeypatch.setattr("steward.features.voice_video.transcribe_voice", AsyncMock(return_value="мат мат"))
    monkeypatch.setattr(
        "steward.features.voice_video.create_transcription_reply",
        AsyncMock(return_value="мат мат"),
    )

    await feature._run_auto_transcription(ctx, "request-id", _pending(), source_message, bot_message)

    ctx.metrics.inc.assert_not_called()
    source_message.set_reaction.assert_not_called()
    assert repo.db.curse_punishment_debts == []

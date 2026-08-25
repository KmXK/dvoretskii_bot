from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from steward.data.models.curse import CurseParticipant, CursePunishment
from steward.features.transcribe import (
    TranscribeFeature,
    _AwaitMediaStep,
    _parse_output_options,
)
from steward.framework.types import from_chat_context
from steward.session.context import ChatStepContext
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


def test_transcribe_output_options_keep_current_defaults():
    assert _parse_output_options("") == (True, True)
    assert _parse_output_options("full=off") == (False, True)
    assert _parse_output_options("summary=off") == (True, False)
    assert _parse_output_options("summary=on full=off") == (False, True)


def test_transcribe_output_options_reject_empty_or_unknown_output():
    assert _parse_output_options("full=off summary=off") is None
    assert _parse_output_options("text=off") is None
    assert _parse_output_options("full=maybe") is None


async def test_transcribe_session_keeps_forwarded_original_author():
    repo = make_repository()
    base = make_text_context("ignored", repo=repo)
    message = base.message
    message.voice = SimpleNamespace(file_id="voice-id")
    message.video_note = None
    message.forward_origin = SimpleNamespace(
        sender_user=SimpleNamespace(
            id=999,
            username="original",
            first_name="Original",
        )
    )
    session_context = {}
    context = ChatStepContext(
        repository=base.repository,
        bot=base.bot,
        client=base.client,
        update=base.update,
        tg_context=base.tg_context,
        metrics=base.metrics,
        message=message,
        session_context=session_context,
    )

    handled = await _AwaitMediaStep().chat(context)

    assert handled
    assert session_context["speaker_user_id"] == 999
    assert session_context["speaker_username"] == "original"
    assert session_context["speaker_first_name"] == "Original"
    assert session_context["speaker_fallback_name"] is None


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


async def test_transcribe_command_attributes_forward_to_original_author(monkeypatch):
    repo = _prepare_repo()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    source_message = ctx.message
    source_message.forward_origin = SimpleNamespace(
        sender_user=SimpleNamespace(
            id=999,
            username="original",
            first_name="Original",
        )
    )
    create_reply = AsyncMock(return_value="привет")

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=Path("/tmp/audio.ogg")))
    monkeypatch.setattr(
        "steward.features.transcribe.create_transcription_reply",
        create_reply,
    )

    await feature._transcribe(
        ctx,
        file_id="file-id",
        is_video_note=False,
        source_message=source_message,
    )

    assert create_reply.await_args.args[3:7] == (
        999,
        "original",
        None,
        "Original",
    )
    ctx.metrics.inc.assert_not_called()


async def test_transcribe_command_counts_curses_for_self_forward(monkeypatch):
    repo = _prepare_repo()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    source_message = ctx.message
    source_message.forward_origin = SimpleNamespace(
        sender_user=SimpleNamespace(
            id=DEFAULT_USER_ID,
            username="testuser",
            first_name="Test",
        )
    )

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
    assert repo.db.curse_punishment_debts[0].user_id == DEFAULT_USER_ID


async def test_transcribe_command_ignores_external_reply_without_source_author(monkeypatch):
    repo = _prepare_repo()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo, metrics=MagicMock()))
    reply_target = ctx.message
    reply_target.forward_origin = None
    external_reply = SimpleNamespace(
        origin=SimpleNamespace(
            sender_user=SimpleNamespace(
                id=999,
                username="external",
                first_name="External",
            )
        )
    )
    create_reply = AsyncMock(return_value="мат мат")

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=Path("/tmp/audio.ogg")))
    monkeypatch.setattr(
        "steward.features.transcribe.create_transcription_reply",
        create_reply,
    )

    await feature._transcribe(
        ctx,
        file_id="file-id",
        is_video_note=False,
        source_message=reply_target,
        curse_source_message=None,
        speaker_source=external_reply,
    )

    assert create_reply.await_args.args[3:7] == (
        999,
        "external",
        None,
        "External",
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


async def test_transcribe_downloads_remote_file_to_temporary_path(monkeypatch):
    repo = make_repository()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo))
    downloaded_paths: list[Path] = []

    async def fake_fetch(bot, file_id, destination):
        assert bot is ctx.bot
        assert file_id == "remote-file-id"
        destination.write_bytes(b"audio")
        downloaded_paths.append(destination)
        return destination

    monkeypatch.setattr(
        "steward.features.transcribe.fetch_tg_file_to",
        fake_fetch,
    )

    audio_path = await feature._resolve_audio_path(ctx, "remote-file-id")

    assert audio_path == downloaded_paths[0]
    assert audio_path.read_bytes() == b"audio"
    feature._remove_audio_path(audio_path)
    assert not audio_path.exists()


async def test_transcribe_removes_temporary_file_after_processing(monkeypatch, tmp_path):
    repo = make_repository()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo))
    source_message = ctx.message
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"audio")

    monkeypatch.setattr(
        feature,
        "_resolve_audio_path",
        AsyncMock(return_value=audio_path),
    )
    monkeypatch.setattr(
        "steward.features.transcribe.create_transcription_reply",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        feature,
        "_process_transcribed_curses",
        AsyncMock(),
    )

    await feature._transcribe(
        ctx,
        file_id="file-id",
        is_video_note=False,
        source_message=source_message,
    )

    assert not audio_path.exists()


async def test_transcribe_passes_selected_output_options(monkeypatch, tmp_path):
    repo = make_repository()
    feature = _make_feature(repo)
    ctx = from_chat_context(make_text_context("ignored", repo=repo))
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"audio")
    create_reply = AsyncMock(return_value="text")

    monkeypatch.setattr(feature, "_resolve_audio_path", AsyncMock(return_value=audio_path))
    monkeypatch.setattr("steward.features.transcribe.create_transcription_reply", create_reply)
    monkeypatch.setattr(feature, "_process_transcribed_curses", AsyncMock())

    await feature._transcribe(
        ctx,
        file_id="file-id",
        is_video_note=False,
        source_message=ctx.message,
        full_text=False,
        summarize=True,
    )

    assert create_reply.await_args.kwargs["include_full_text"] is False
    assert create_reply.await_args.kwargs["summarize"] is True

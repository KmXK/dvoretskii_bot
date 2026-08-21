from unittest.mock import AsyncMock, MagicMock

from steward.features.voice_video.transcription import create_transcription_reply


def _repository():
    repository = MagicMock()
    repository.db.users = []
    repository.db.ai_messages = {}
    repository.save = AsyncMock()
    return repository


async def test_full_text_without_summary_skips_summary_model(monkeypatch, tmp_path):
    summary_stream = AsyncMock()
    register_target = AsyncMock()
    monkeypatch.setattr(
        "steward.features.voice_video.transcription._summary_stream",
        summary_stream,
    )
    monkeypatch.setattr(
        "steward.features.voice_video.transcription._register_ai_reply_target",
        register_target,
    )
    reply_target = MagicMock()
    reply_target.reply_html = AsyncMock(return_value=MagicMock())

    result = await create_transcription_reply(
        _repository(),
        reply_target,
        tmp_path / "audio.ogg",
        None,
        None,
        None,
        pretranscribed="Полный распознанный текст",
        include_full_text=True,
        summarize=False,
    )

    assert result == "Полный распознанный текст"
    summary_stream.assert_not_awaited()
    sent_html = reply_target.reply_html.await_args.args[0]
    assert "Полный распознанный текст" in sent_html


async def test_summary_without_full_text_hides_transcription(monkeypatch, tmp_path):
    async def chunks():
        yield "Короткая выжимка"

    stream_summary = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(
        "steward.features.voice_video.transcription._summary_stream",
        AsyncMock(return_value=chunks()),
    )
    monkeypatch.setattr(
        "steward.features.voice_video.transcription._stream_summary_with_spoiler",
        stream_summary,
    )
    reply_target = MagicMock()

    result = await create_transcription_reply(
        _repository(),
        reply_target,
        tmp_path / "audio.ogg",
        None,
        None,
        None,
        pretranscribed="Скрытый полный текст",
        include_full_text=False,
        summarize=True,
    )

    assert result == "Скрытый полный текст"
    assert stream_summary.await_args.args[2] == ""


async def test_transcription_requires_at_least_one_output(tmp_path):
    try:
        await create_transcription_reply(
            _repository(),
            MagicMock(),
            tmp_path / "audio.ogg",
            None,
            None,
            None,
            pretranscribed="text",
            include_full_text=False,
            summarize=False,
        )
    except ValueError as error:
        assert "At least one" in str(error)
    else:
        raise AssertionError("ValueError was not raised")

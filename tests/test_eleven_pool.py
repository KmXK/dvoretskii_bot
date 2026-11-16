from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from steward.helpers import eleven_pool


class ApiError(Exception):
    def __init__(self, code, status_code=400):
        self.body = {"detail": {"code": code}}
        self.status_code = status_code
        super().__init__(code)


@pytest.fixture(autouse=True)
def reset_pool(monkeypatch):
    eleven_pool._current.clear()
    eleven_pool._exhausted_until.clear()
    monkeypatch.setenv("ELEVENLABS_API_KEYS", "first, second, third")


async def test_quota_rotates_and_keeps_using_current_key():
    call = AsyncMock(side_effect=[ApiError("quota_exceeded"), "ok", "again"])
    assert await eleven_pool.call_with_eleven_keys(call) == "ok"
    assert await eleven_pool.call_with_eleven_keys(call) == "again"
    assert [item.args[0] for item in call.await_args_list] == ["first", "second", "second"]


async def test_other_errors_do_not_rotate():
    call = AsyncMock(side_effect=ApiError("invalid_api_key", 401))
    with pytest.raises(ApiError):
        await eleven_pool.call_with_eleven_keys(call)
    assert call.await_count == 1
    assert not eleven_pool._exhausted_until


async def test_exhausted_keys_wait_and_become_available_again(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(eleven_pool.time, "monotonic", lambda: now[0])
    call = AsyncMock(side_effect=[ApiError("insufficient_credits")] * 3)
    with pytest.raises(ApiError):
        await eleven_pool.call_with_eleven_keys(call)
    with pytest.raises(RuntimeError, match="quota exhausted"):
        await eleven_pool.call_with_eleven_keys(call)
    assert call.await_count == 3
    now[0] += eleven_pool._COOLDOWN_SECONDS
    call.side_effect = None
    call.return_value = "ok"
    assert await eleven_pool.call_with_eleven_keys(call) == "ok"


async def test_legacy_key_is_used_when_pool_unset(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEYS")
    call = AsyncMock(return_value="ok")
    assert await eleven_pool.call_with_eleven_keys(call, "old-key") == "ok"
    call.assert_awaited_once_with("old-key")


def test_quota_does_not_match_request_or_rate_limits():
    assert not eleven_pool._quota_error(ApiError("max_character_limit_exceeded"))
    assert not eleven_pool._quota_error(ApiError("rate_limit_exceeded", 429))
    assert eleven_pool._quota_error(SimpleNamespace(status_code=402, body=None))


async def test_transcription_uses_next_key(monkeypatch):
    from steward.helpers import stt

    convert = AsyncMock(side_effect=[ApiError("quota_exceeded"), "transcript"])
    monkeypatch.setattr(stt, "_elevenlabs_transcribe_with_key", convert)
    assert await stt._elevenlabs_transcribe(b"audio") == "transcript"
    assert [call.args[1] for call in convert.await_args_list] == ["first", "second"]


async def test_synthesis_uses_next_key(monkeypatch):
    from steward.helpers.news_video import tts

    keys = []

    def synthesize(text, voice_id, model_id, api_key):
        keys.append(api_key)
        if api_key == "first":
            raise ApiError("quota_exceeded")
        return b"audio"

    monkeypatch.setattr(tts, "_tts_one_eleven_sync", synthesize)
    assert await tts._synthesize_with_keys("hello", "voice", "model") == b"audio"
    assert keys == ["first", "second"]

from pathlib import Path

import pytest

from steward.features.download import yt


class FakeDownloadInfo:
    def __init__(self, bitrate_in_kbps: int, preview: bool = False):
        self.bitrate_in_kbps = bitrate_in_kbps
        self.codec = "mp3"
        self.preview = preview

    def download(self, filename: str) -> None:
        Path(filename).write_bytes(str(self.bitrate_in_kbps).encode())


class FakeTrack:
    def get_download_info(self) -> list[FakeDownloadInfo]:
        return [
            FakeDownloadInfo(128, preview=True),
            FakeDownloadInfo(192),
            FakeDownloadInfo(320),
        ]


class FakeYandexMusicClient:
    def __init__(self, token: str):
        assert token == "token"

    def init(self):
        return self

    def tracks(self, track_ids: list[str]) -> list[FakeTrack]:
        assert track_ids == ["155227395"]
        return [FakeTrack()]


async def test_download_yandex_audio_uses_best_full_mp3(monkeypatch, tmp_path):
    monkeypatch.setenv("YANDEX_MUSIC_TOKEN", "token")
    monkeypatch.setattr(yt, "YandexMusicClient", FakeYandexMusicClient)

    filepath = await yt.download_yandex_audio(
        "https://music.yandex.ru/album/43722989/track/155227395?utm_source=copy",
        str(tmp_path),
    )

    assert Path(filepath).read_bytes() == b"320"


async def test_download_yandex_audio_requires_token(monkeypatch, tmp_path):
    monkeypatch.delenv("YANDEX_MUSIC_TOKEN", raising=False)

    with pytest.raises(yt.YandexMusicDownloadError, match="нужен OAuth-токен"):
        await yt.download_yandex_audio(
            "https://music.yandex.ru/track/155227395",
            str(tmp_path),
        )

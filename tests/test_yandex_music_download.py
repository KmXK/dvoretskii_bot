from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mutagen.id3 import ID3
from PIL import Image

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
    title = "Название песни"
    artists = [SimpleNamespace(name="Исполнитель"), SimpleNamespace(name="Гость")]
    cover_uri = "cover/%%"

    def download_cover_bytes(self, size):
        assert size == "300x300"
        output = BytesIO()
        Image.new("RGB", (600, 600), "red").save(output, "PNG")
        return output.getvalue()

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

    audio = await yt.download_yandex_audio(
        "https://music.yandex.ru/album/43722989/track/155227395?utm_source=copy",
        str(tmp_path),
    )

    assert Path(audio.path).name == "Исполнитель, Гость - Название песни.mp3"
    assert Path(audio.path).read_bytes().endswith(b"320")
    assert audio.title == "Название песни"
    assert audio.performer == "Исполнитель, Гость"
    tags = ID3(audio.path)
    assert tags["TIT2"].text == [audio.title]
    assert tags["TPE1"].text == [audio.performer]
    assert tags.getall("APIC")[0].data == audio.thumbnail
    with Image.open(BytesIO(audio.thumbnail)) as cover:
        assert cover.format == "JPEG"
        assert cover.size == (300, 300)


def test_yandex_music_filename_is_cross_platform_safe():
    assert yt._yandex_music_filename('  Песня: live / remix?  ') == "Песня live remix.mp3"


async def test_download_yandex_audio_requires_token(monkeypatch, tmp_path):
    monkeypatch.delenv("YANDEX_MUSIC_TOKEN", raising=False)

    with pytest.raises(yt.YandexMusicDownloadError, match="нужен OAuth-токен"):
        await yt.download_yandex_audio(
            "https://music.yandex.ru/track/155227395",
            str(tmp_path),
        )


async def test_music_without_artist_or_cover_still_downloads(monkeypatch, tmp_path):
    monkeypatch.setenv("YANDEX_MUSIC_TOKEN", "token")
    monkeypatch.setattr(yt, "YandexMusicClient", FakeYandexMusicClient)
    monkeypatch.setattr(FakeTrack, "artists", [])
    monkeypatch.setattr(FakeTrack, "cover_uri", None)
    audio = await yt.download_yandex_audio("https://music.yandex.ru/track/155227395", str(tmp_path))
    assert Path(audio.path).name == "Название песни.mp3"
    assert audio.performer is None
    assert audio.thumbnail is None
    assert ID3(audio.path)["TIT2"].text == ["Название песни"]


async def test_cover_failure_keeps_audio(monkeypatch, tmp_path):
    monkeypatch.setenv("YANDEX_MUSIC_TOKEN", "token")
    monkeypatch.setattr(yt, "YandexMusicClient", FakeYandexMusicClient)
    monkeypatch.setattr(FakeTrack, "download_cover_bytes", lambda *a, **kw: b"invalid image")
    audio = await yt.download_yandex_audio("https://music.yandex.ru/track/155227395", str(tmp_path))
    assert audio.thumbnail is None
    assert ID3(audio.path)["TPE1"].text == [audio.performer]


async def test_chat_music_sends_artist_title_cover(monkeypatch):
    async def download(url, directory):
        path = Path(directory) / "Artist - Song.mp3"
        path.write_bytes(b"audio")
        return yt.YandexAudio(str(path), "Song", "Artist", b"cover")
    monkeypatch.setattr(yt, "download_yandex_audio", download)
    message = SimpleNamespace(reply_audio=AsyncMock())
    await yt.load_yandex_music(None, "https://music.yandex.ru/track/1", message)
    assert message.reply_audio.await_args.kwargs == {
        "filename": "Artist - Song.mp3", "title": "Song",
        "performer": "Artist", "thumbnail": b"cover",
    }


async def test_empty_download_is_rejected_before_tagging(monkeypatch, tmp_path):
    monkeypatch.setenv("YANDEX_MUSIC_TOKEN", "token")
    monkeypatch.setattr(yt, "YandexMusicClient", FakeYandexMusicClient)
    monkeypatch.setattr(FakeDownloadInfo, "download", lambda self, filename: Path(filename).touch())
    with pytest.raises(yt.YandexMusicDownloadError, match="пустой файл"):
        await yt.download_yandex_audio("https://music.yandex.ru/track/155227395", str(tmp_path))


def test_tagging_preserves_other_tags_and_replaces_old_metadata(tmp_path):
    from mutagen.id3 import APIC, TALB, TIT2, TPE1

    path = tmp_path / "track.mp3"
    path.write_bytes(b"audio")
    tags = ID3()
    tags.add(TALB(encoding=3, text="Album"))
    tags.add(TIT2(encoding=3, text="Old title"))
    tags.add(TPE1(encoding=3, text="Old artist"))
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, data=b"old cover"))
    tags.save(path)
    audio = yt.YandexAudio(str(path), "New title", "New artist", b"new cover")
    yt._tag_yandex_audio(audio)
    yt._tag_yandex_audio(audio)
    tags = ID3(path)
    assert tags["TALB"].text == ["Album"]
    assert tags["TIT2"].text == ["New title"]
    assert tags["TPE1"].text == ["New artist"]
    assert len(tags.getall("APIC")) == 1
    assert tags.getall("APIC")[0].data == b"new cover"
    # Unavailable source artwork must not remove an existing embedded cover.
    yt._tag_yandex_audio(yt.YandexAudio(str(path), "New title", "New artist"))
    assert ID3(path).getall("APIC")[0].data == b"new cover"

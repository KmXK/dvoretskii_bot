import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yt_dlp

from steward.features.download import yt
from steward.helpers.media import probe_media_streams


def _format(name, resolution, codec="h265", **kwargs):
    return {
        "format_id": name,
        "url": f"https://example.com/{name}.mp4",
        "ext": "mp4",
        "vcodec": codec,
        "acodec": "aac",
        "width": resolution,
        "height": resolution * 16 // 9,
        "preference": -1,
        **kwargs,
    }


@pytest.mark.parametrize(
    "formats,expected",
    [
        ([_format("play", 576, "h264"), _format("hd", 1080)], "hd"),
        ([_format("play_addr_h264", 576, "h264"), _format("hd", 720)], "hd"),
        ([_format("hd", 1080), _format("uhd", 2160)], "hd"),
        ([_format("low_audio", 1080, "h264", abr=32),
          _format("good_audio", 1080, abr=128)], "good_audio"),
        ([_format("play", 720, "h264"), _format("unplayable", 1080, "bytevc2")], "play"),
        ([_format("play", 720), _format("download", 1080, "h264")], "play"),
        ([_format("download", 720, "h264")], "download"),
    ],
)
def test_tiktok_selects_best_playable_video(formats, expected):
    formats.append({
        "format_id": "audio", "url": "https://example.com/music.mp3",
        "vcodec": "none", "acodec": "mp3", "abr": 320,
    })
    with yt_dlp.YoutubeDL({
        "format": yt.TIKTOK_VIDEO_FORMAT,
        "format_sort": yt.TIKTOK_FORMAT_SORT,
        "quiet": True,
    }) as ydl:
        selected = ydl.process_ie_result({
            "id": "test", "title": "test", "formats": formats,
        }, download=False)

    assert selected["format_id"] == expected
    assert "requested_formats" not in selected


def _video(path, bitrate, duration=1):
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=90x160:rate=25",
    ]
    if bitrate:
        command += [
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
            "-c:a", "aac", "-b:a", bitrate,
        ]
    command += ["-t", str(duration), "-c:v", "libx264", str(path)]
    subprocess.run(command, check=True)
    return path


def _stream_hash(path, stream):
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", f"0:{stream}:0",
        "-c", "copy", "-f", "hash", "-hash", "sha256", "-",
    ])


def _mock_download(monkeypatch, primary, donor, *, primary_error=None, donor_error=None):
    def factory(opts):
        def extract(url):
            is_primary = opts["format"] == yt.TIKTOK_VIDEO_FORMAT
            error = primary_error if is_primary else donor_error
            if error:
                raise error
            shutil.copyfile(primary if is_primary else donor, opts["outtmpl"])
            return {
                "id": "test", "width": 90, "height": 160, "duration": 1,
                "format_id": "hd" if is_primary else "download",
            }
        return MagicMock(extract_info=extract)
    monkeypatch.setattr(yt.yt_dlp, "YoutubeDL", factory)


async def _download(output):
    output.mkdir()
    return await yt.download_video_file(
        "https://www.tiktok.com/@test/video/123", str(output),
        type_name="inline", video_format=yt.TIKTOK_VIDEO_FORMAT,
        fallback_format=yt.TIKTOK_FALLBACK_FORMAT,
    )


@pytest.mark.parametrize("source_bitrate", [None, "32k"])
async def test_tiktok_copies_better_audio_and_preserves_video(
    monkeypatch, tmp_path, source_bitrate,
):
    primary = _video(tmp_path / "primary.mp4", source_bitrate)
    donor = _video(tmp_path / "donor.mp4", "128k")
    _mock_download(monkeypatch, primary, donor)

    info, output = await _download(tmp_path / "output")

    assert _stream_hash(output, "v") == _stream_hash(primary, "v")
    assert _stream_hash(output, "a") == _stream_hash(donor, "a")
    assert info["format_id"] == "hd"
    assert info["abr"] > 32


async def test_tiktok_does_not_include_download_outro(monkeypatch, tmp_path):
    primary = _video(tmp_path / "primary.mp4", "32k")
    donor = _video(tmp_path / "donor.mp4", "128k", duration=5)
    _mock_download(monkeypatch, primary, donor)

    _, output = await _download(tmp_path / "output")
    streams = await probe_media_streams(Path(output))

    assert all(float(s["duration"]) < 1.1 for s in streams)
    assert _stream_hash(output, "v") == _stream_hash(primary, "v")


@pytest.mark.parametrize("source_bitrate,donor_bitrate,duration", [
    ("192k", "32k", 1), ("32k", "128k", 0.4), ("32k", None, 1),
])
async def test_tiktok_keeps_audio_when_donor_is_worse_or_incomplete(
    monkeypatch, tmp_path, source_bitrate, donor_bitrate, duration,
):
    primary = _video(tmp_path / "primary.mp4", source_bitrate)
    donor = _video(tmp_path / "donor.mp4", donor_bitrate, duration=duration)
    _mock_download(monkeypatch, primary, donor)

    _, output = await _download(tmp_path / "output")

    assert Path(output).read_bytes() == primary.read_bytes()


async def test_tiktok_keeps_video_when_audio_upgrade_fails(monkeypatch, tmp_path):
    primary = _video(tmp_path / "primary.mp4", "32k")
    _mock_download(
        monkeypatch, primary, None,
        donor_error=yt_dlp.utils.DownloadError("unavailable"),
    )

    _, output = await _download(tmp_path / "output")

    assert Path(output).read_bytes() == primary.read_bytes()


async def test_tiktok_falls_back_when_hd_is_unavailable(monkeypatch, tmp_path):
    donor = _video(tmp_path / "donor.mp4", "128k")
    _mock_download(
        monkeypatch, None, donor,
        primary_error=yt_dlp.utils.DownloadError("unavailable"),
    )

    _, output = await _download(tmp_path / "output")

    assert Path(output).read_bytes() == donor.read_bytes()


@pytest.mark.parametrize("filenames", [
    ["file.part"], ["file.f137.mp4.part", "file.f140.m4a"],
    ["file.f137.mp4", "file.f140.m4a"], [],
])
async def test_download_rejects_incomplete_or_unmerged_files(monkeypatch, tmp_path, filenames):
    def extract(url):
        for filename in filenames:
            (tmp_path / filename).write_bytes(b"incomplete")
        return {}
    monkeypatch.setattr(
        yt.yt_dlp, "YoutubeDL", MagicMock(return_value=MagicMock(extract_info=extract)),
    )

    with pytest.raises(RuntimeError, match="готовый видеофайл"):
        await yt.download_video_file("https://example.com/video", str(tmp_path))

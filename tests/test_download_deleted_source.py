import json
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from telegram import Message

from steward.features.download import callbacks, yt
from tests.conftest import CHAT_ID, MockRequest, make_bot, make_repository


class DeletedSourceRequest(MockRequest):
    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.split("/")[-1]
        if endpoint not in {"sendVideo", "sendPhoto", "sendMediaGroup", "sendAudio", "sendRichMessage"}:
            return await super().do_request(url, method, request_data=request_data, **kwargs)

        params = dict(request_data.parameters)
        self.calls.append((endpoint, params))
        reply = params.get("reply_parameters") or {}
        if not reply.get("allow_sending_without_reply"):
            return 400, json.dumps({
                "ok": False, "error_code": 400,
                "description": "Bad Request: Message to be replied not found",
            }).encode()

        result = {
            "message_id": 100, "date": int(time.time()),
            "chat": {"id": CHAT_ID, "type": "supergroup", "title": "Test"},
        }
        if endpoint == "sendMediaGroup":
            result = [result, {**result, "message_id": 101}]
        return 200, json.dumps({"ok": True, "result": result}).encode()


@pytest.mark.parametrize("loader", ["instagram", "tiktok", "video", "photo", "album", "slideshow"])
async def test_download_delivers_each_video_after_sources_are_deleted(
    monkeypatch, tmp_path, loader,
):
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    request = DeletedSourceRequest()
    bot, app = await make_bot(request)
    repository = make_repository()

    @asynccontextmanager
    async def download(url, **kwargs):
        with video_path.open("rb") as file:
            yield file

    monkeypatch.setattr(callbacks, "download_file", download)
    monkeypatch.setattr(yt, "download_video_file", AsyncMock(return_value=(
        {"duration": 200, "width": 90, "height": 160}, str(video_path),
    )))

    try:
        for message_id in (41, 42):
            message = Message.de_json({
                "message_id": message_id, "date": int(time.time()),
                "chat": {"id": CHAT_ID, "type": "supergroup", "title": "Test"},
            }, bot)
            if loader == "instagram":
                await callbacks.download_and_send_medias(
                    repository, message, [("https://cdn.example/video.mp4", True)],
                )
            elif loader == "tiktok":
                await yt.make_video_loader("tiktok")(
                    repository, "https://www.tiktok.com/@test/video/123", message,
                )
            else:
                paths = {
                    "video": [str(video_path)], "photo": [str(image_path)],
                    "album": [str(image_path), str(video_path)],
                    "slideshow": [str(image_path), str(image_path)],
                }
                await callbacks.send_media_files(message, paths[loader], retries_count=1)

        sent = [params for endpoint, params in request.calls if endpoint.startswith("send")]
        assert len(sent) == 2
        assert [params["reply_parameters"]["message_id"] for params in sent] == [41, 42]
        assert all(params["chat_id"] == CHAT_ID for params in sent)
    finally:
        await app.shutdown()

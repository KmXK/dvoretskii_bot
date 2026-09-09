import html
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import steward.bot.inline_download as inline_download
import steward.features.download.yt as download_youtube
from steward.features.download.yt import (
    THREADS_MEDIA_HEADERS,
    _fetch_threads_page,
    _threads_post_medias,
    build_dispatch,
    load_threads,
    parse_threads_page,
    resolve_threads_medias,
)


def _image(url: str, width: int, height: int) -> dict:
    return {
        "url": url,
        "width": width,
        "height": height,
    }


def _media(
    *,
    images: list[dict] | None = None,
    videos: list[str] | None = None,
) -> dict:
    return {
        "image_versions2": {"candidates": images or []},
        "video_versions": [
            {"url": url, "type": index + 101}
            for index, url in enumerate(videos or [])
        ],
    }


def _post(
    shortcode: str,
    *,
    caption: str = "Текст поста",
    media: dict | None = None,
    carousel: list[dict] | None = None,
) -> dict:
    result = {
        "code": shortcode,
        "caption": {"text": caption},
        "user": {"username": "author"},
    }
    result.update(media or {})
    if carousel is not None:
        result["carousel_media"] = carousel
    return result


def _page(
    posts: list[dict],
    *,
    canonical_url: str = "https://www.threads.com/@author/post/Target123",
    description: str = "Описание из meta",
    invalid_script: bool = False,
) -> str:
    scripts = '<script type="application/json">{broken</script>' if invalid_script else ""
    scripts += (
        '<script data-sjs type="application/json">'
        + json.dumps({"nested": {"posts": posts}}, ensure_ascii=False)
        + "</script>"
    )
    return (
        f'<meta property="og:url" content="{html.escape(canonical_url, quote=True)}">'
        f'<meta property="og:description" content="{html.escape(description, quote=True)}">'
        + scripts
    )


def test_parse_threads_single_image_chooses_largest_candidate():
    page = _page([
        _post(
            "Target123",
            media=_media(
                images=[
                    _image("https://scontent.test.cdninstagram.com/small.jpg", 320, 240),
                    _image("https://scontent.test.cdninstagram.com/large.jpg", 1920, 1080),
                    _image("https://scontent.test.cdninstagram.com/tall.jpg", 1080, 1350),
                ],
            ),
        )
    ])

    medias, metadata = parse_threads_page(
        page,
        "https://www.threads.com/@author/post/Target123",
        "https://www.threads.com/@author/post/Target123",
    )

    assert medias == [("https://scontent.test.cdninstagram.com/large.jpg", False)]
    assert metadata == {
        "description": "Текст поста",
        "title": "Текст поста",
        "uploader": "author",
    }


def test_parse_threads_video_does_not_duplicate_cover_image():
    page = _page([
        _post(
            "Target123",
            media=_media(
                images=[_image("https://scontent.test.cdninstagram.com/cover.jpg", 1920, 1080)],
                videos=[
                    "https://scontent.test.cdninstagram.com/video.mp4",
                    "https://scontent.test.cdninstagram.com/video.mp4",
                ],
            ),
        )
    ])

    medias, _ = parse_threads_page(
        page,
        "https://www.threads.com/@author/post/Target123",
        "https://www.threads.com/@author/post/Target123",
    )

    assert medias == [("https://scontent.test.cdninstagram.com/video.mp4", True)]


def test_threads_video_chooses_largest_version():
    post = _post(
        "Target123",
        media={
            "video_versions": [
                {
                    "url": "https://scontent.test.cdninstagram.com/small.mp4",
                    "width": 640,
                    "height": 360,
                    "bitrate": 500,
                },
                {
                    "url": "https://scontent.test.cdninstagram.com/large.mp4",
                    "width": 1920,
                    "height": 1080,
                    "bitrate": 2000,
                },
            ],
        },
    )

    assert _threads_post_medias(post) == [
        ("https://scontent.test.cdninstagram.com/large.mp4", True),
    ]


def test_parse_threads_mixed_carousel_preserves_order():
    page = _page([
        _post(
            "Target123",
            carousel=[
                _media(images=[_image("https://scontent.test.cdninstagram.com/one.jpg", 1000, 1000)]),
                _media(
                    images=[_image("https://scontent.test.cdninstagram.com/cover.jpg", 1000, 1000)],
                    videos=["https://scontent.test.cdninstagram.com/two.mp4"],
                ),
                _media(images=[_image("https://scontent.test.cdninstagram.com/three.jpg", 800, 1200)]),
            ],
        )
    ])

    medias, _ = parse_threads_page(
        page,
        "https://www.threads.com/@author/post/Target123",
        "https://www.threads.com/@author/post/Target123",
    )

    assert medias == [
        ("https://scontent.test.cdninstagram.com/one.jpg", False),
        ("https://scontent.test.cdninstagram.com/two.mp4", True),
        ("https://scontent.test.cdninstagram.com/three.jpg", False),
    ]


def test_parse_threads_selects_target_instead_of_related_post():
    related = _post(
        "Related456",
        media=_media(videos=["https://scontent.test.cdninstagram.com/wrong.mp4"]),
    )
    target = _post(
        "Target123",
        media=_media(images=[_image("https://scontent.test.cdninstagram.com/right.jpg", 1000, 1000)]),
    )
    page = _page([target, related])

    medias, _ = parse_threads_page(
        page,
        "https://www.threads.com/@author/post/Target123",
        "https://www.threads.com/@author/post/Target123",
    )

    assert medias == [("https://scontent.test.cdninstagram.com/right.jpg", False)]


def test_parse_threads_current_data_sjs_shape():
    target = _post(
        "Target123",
        media=_media(videos=["https://scontent.test.cdninstagram.com/video.mp4"]),
    )
    related = _post(
        "Related456",
        media=_media(images=[
            _image("https://scontent.test.cdninstagram.com/related.jpg", 1000, 1000)
        ]),
    )
    data = {
        "require": [[
            None,
            None,
            None,
            {
                "__bbox": {
                    "require": [[
                        None,
                        None,
                        None,
                        {
                            "__bbox": {
                                "result": {
                                    "data": {
                                        "data": {
                                            "edges": [{
                                                "node": {
                                                    "thread_items": [
                                                        {"post": related},
                                                        {"post": target},
                                                    ]
                                                }
                                            }]
                                        }
                                    }
                                }
                            }
                        },
                    ]]
                }
            },
        ]]
    }
    page = (
        '<meta property="og:url" content="https://www.threads.com/@author/post/Target123">'
        '<script type="application/json" data-sjs>'
        + json.dumps(data)
        + "</script>"
    )

    medias, _ = parse_threads_page(
        page,
        "https://www.threads.com/@author/post/Target123",
        "https://www.threads.com/@author/post/Target123",
    )

    assert medias == [("https://scontent.test.cdninstagram.com/video.mp4", True)]


def test_parse_threads_uses_canonical_url_for_share_link():
    target = _post(
        "Target123",
        caption="",
        media=_media(images=[_image("https://scontent.test.cdninstagram.com/image.jpg", 1000, 1000)]),
    )
    page = _page(
        [target],
        canonical_url="https://www.threads.com/@author/post/Target123",
        description="Описание & детали",
        invalid_script=True,
    )

    medias, metadata = parse_threads_page(
        page,
        "https://www.threads.com/share/ShareToken",
        "https://www.threads.net/share/ShareToken",
    )

    assert medias == [("https://scontent.test.cdninstagram.com/image.jpg", False)]
    assert metadata["description"] == "Описание & детали"


def test_parse_threads_handles_malformed_caption_and_user():
    post = _post(
        "Target123",
        media=_media(images=[
            _image("https://scontent.test.cdninstagram.com/image.jpg", 1000, 1000)
        ]),
    )
    post["caption"] = "unexpected"
    post["user"] = "unexpected"

    _, metadata = parse_threads_page(
        _page([post], description="Описание из meta"),
        "https://www.threads.com/@author/post/Target123",
        "https://www.threads.com/@author/post/Target123",
    )

    assert metadata == {
        "description": "Описание из meta",
        "title": "Описание из meta",
        "uploader": None,
    }


def test_parse_threads_skips_invalid_media_urls():
    post = _post(
        "Target123",
        media=_media(
            images=[
                _image("javascript:alert(1)", 2000, 2000),
                _image("https://attacker.example/private", 3000, 3000),
                _image("https://scontent.test.cdninstagram.com/image.jpg", 1000, 1000),
            ],
        ),
    )

    medias, _ = parse_threads_page(
        _page([post]),
        "https://www.threads.com/@author/post/Target123",
        "https://www.threads.com/@author/post/Target123",
    )

    assert medias == [("https://scontent.test.cdninstagram.com/image.jpg", False)]


def test_parse_threads_rejects_missing_target():
    page = _page([
        _post(
            "Related456",
            media=_media(videos=["https://scontent.test.cdninstagram.com/wrong.mp4"]),
        )
    ])

    with pytest.raises(ValueError, match="не отдал данные"):
        parse_threads_page(
            page,
            "https://www.threads.com/@author/post/Target123",
            "https://www.threads.com/@author/post/Target123",
        )


def test_parse_threads_rejects_text_only_post():
    page = _page([_post("Target123")])

    with pytest.raises(ValueError, match="нет доступных"):
        parse_threads_page(
            page,
            "https://www.threads.com/@author/post/Target123",
            "https://www.threads.com/@author/post/Target123",
        )


def test_threads_post_medias_deduplicates_carousel_urls():
    post = _post(
        "Target123",
        carousel=[
            _media(images=[_image("https://scontent.test.cdninstagram.com/image.jpg", 1000, 1000)]),
            _media(images=[_image("https://scontent.test.cdninstagram.com/image.jpg", 1000, 1000)]),
        ],
    )

    assert _threads_post_medias(post) == [
        ("https://scontent.test.cdninstagram.com/image.jpg", False),
    ]


def test_threads_post_medias_limits_carousel_to_twenty_items():
    post = _post(
        "Target123",
        carousel=[
            _media(
                images=[
                    _image(
                        f"https://scontent.test.cdninstagram.com/{index}.jpg",
                        1000,
                        1000,
                    )
                ]
            )
            for index in range(25)
        ],
    )

    medias = _threads_post_medias(post)

    assert len(medias) == 20
    assert medias[-1] == (
        "https://scontent.test.cdninstagram.com/19.jpg",
        False,
    )


def _threads_response(
    status: int = 200,
    *,
    location: str | None = None,
    page: str = "page",
):
    response = MagicMock()
    response.status = status
    response.headers = {"Location": location} if location else {}
    response.raise_for_status = MagicMock()
    response.text = AsyncMock(return_value=page)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


def _mock_threads_session(monkeypatch, responses: list):
    session = MagicMock()
    session.get.side_effect = responses
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session)
    monkeypatch.setattr(download_youtube.aiohttp, "ClientSession", session_factory)
    return session, session_factory


async def test_resolve_threads_uses_final_redirect_url(monkeypatch):
    page = _page([
        _post(
            "Target123",
            media=_media(videos=["https://scontent.test.cdninstagram.com/video.mp4"]),
        )
    ])
    fetch = AsyncMock(
        return_value=(
            page,
            "https://www.threads.com/@author/post/Target123",
        )
    )
    monkeypatch.setattr(download_youtube, "_fetch_threads_page", fetch)

    medias, metadata = await resolve_threads_medias(
        "https://www.threads.net/t/Target123?xmt=token"
    )

    fetch.assert_awaited_once_with("https://www.threads.net/t/Target123?xmt=token")
    assert medias == [("https://scontent.test.cdninstagram.com/video.mp4", True)]
    assert metadata["uploader"] == "author"


async def test_fetch_threads_page_uses_proxy_and_crawler_headers(monkeypatch):
    redirect = _threads_response(
        302,
        location="https://www.threads.com/@author/post/Target123",
    )
    response = _threads_response()
    session, session_factory = _mock_threads_session(
        monkeypatch,
        [redirect, response],
    )
    connector = object()
    connector_factory = MagicMock(return_value=connector)
    monkeypatch.setenv("DOWNLOAD_PROXY", "socks5://proxy.example:1080")
    monkeypatch.setattr(download_youtube.aiohttp, "ClientSession", session_factory)
    monkeypatch.setattr(
        download_youtube.ProxyConnector,
        "from_url",
        connector_factory,
    )

    page, final_url = await _fetch_threads_page(
        "https://www.threads.net/t/Target123"
    )

    connector_factory.assert_called_once_with("socks5://proxy.example:1080")
    assert session_factory.call_args.kwargs["connector"] is connector
    assert "Googlebot" in session_factory.call_args.kwargs["headers"]["User-Agent"]
    assert session.get.call_args_list[0].args == (
        "https://www.threads.net/t/Target123",
    )
    assert session.get.call_args_list[0].kwargs == {"allow_redirects": False}
    assert session.get.call_args_list[1].args == (
        "https://www.threads.com/@author/post/Target123",
    )
    assert session.get.call_args_list[1].kwargs == {"allow_redirects": False}
    response.raise_for_status.assert_called_once_with()
    assert page == "page"
    assert final_url == "https://www.threads.com/@author/post/Target123"


async def test_fetch_threads_page_rejects_non_threads_source():
    with pytest.raises(ValueError, match="неподдерживаемый адрес"):
        await _fetch_threads_page("http://127.0.0.1/private")


async def test_fetch_threads_page_rejects_external_redirect(monkeypatch):
    redirect = _threads_response(
        302,
        location="http://169.254.169.254/latest/meta-data",
    )
    _mock_threads_session(
        monkeypatch,
        [redirect],
    )
    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)

    with pytest.raises(ValueError, match="перенаправил"):
        await _fetch_threads_page("https://www.threads.com/share/ShareToken")


async def test_load_threads_uses_shared_media_sender(monkeypatch):
    medias = [
        ("https://scontent.test.cdninstagram.com/image.jpg", False),
        ("https://scontent.test.cdninstagram.com/video.mp4", True),
    ]
    resolver = AsyncMock(
        return_value=(
            medias,
            {"description": "Описание Threads"},
        )
    )
    sender = AsyncMock()
    monkeypatch.setattr(download_youtube, "resolve_threads_medias", resolver)
    monkeypatch.setattr(download_youtube, "download_and_send_medias", sender)
    repository = MagicMock()
    message = MagicMock()

    await load_threads(
        repository,
        "https://www.threads.com/@author/post/Target123",
        message,
    )

    resolver.assert_awaited_once()
    sender.assert_awaited_once()
    assert sender.await_args.args[:3] == (repository, message, medias)
    assert sender.await_args.kwargs["use_proxy"] is True
    assert sender.await_args.kwargs["request_headers"] == THREADS_MEDIA_HEADERS
    assert sender.await_args.kwargs["transcription_enabled"] is False
    assert "Описание Threads" in sender.await_args.kwargs["caption"]


async def test_chat_dispatch_has_both_threads_hosts(monkeypatch):
    loader = AsyncMock()
    monkeypatch.setattr(download_youtube, "load_threads", loader)
    repository = MagicMock()
    message = MagicMock()
    dispatch = build_dispatch(repository)

    for host in ("threads.com", "threads.net"):
        await dispatch[host][0](
            f"https://{host}/@author/post/Target123",
            message,
        )

    assert loader.await_count == 2


async def test_inline_threads_loader_uses_shared_resolver(monkeypatch):
    medias = [("https://scontent.test.cdninstagram.com/image.jpg", False)]
    metadata = {"description": "Описание Threads"}
    resolver = AsyncMock(return_value=(medias, metadata))
    uploader = AsyncMock(return_value=[])
    monkeypatch.setattr(inline_download, "resolve_threads_medias", resolver)
    monkeypatch.setattr(inline_download, "_upload_resolved_medias", uploader)
    bot = MagicMock()

    result = await inline_download._upload_threads(
        "https://www.threads.com/@author/post/Target123",
        bot,
    )

    assert result == []
    uploader.assert_awaited_once_with(
        medias,
        metadata,
        bot,
        THREADS_MEDIA_HEADERS,
    )


async def test_inline_resolved_media_closes_contexts_after_partial_failure(monkeypatch):
    good = MagicMock()
    good.__aenter__ = AsyncMock(return_value=MagicMock())
    good.__aexit__ = AsyncMock(return_value=None)
    failed = MagicMock()
    failed.__aenter__ = AsyncMock(side_effect=ValueError("download failed"))
    failed.__aexit__ = AsyncMock(return_value=None)
    contexts = iter([good, failed])
    monkeypatch.setattr(
        inline_download,
        "download_file",
        MagicMock(side_effect=lambda *args, **kwargs: next(contexts)),
    )
    monkeypatch.setattr(inline_download, "_upload_chat_id", MagicMock(return_value=1))

    with pytest.raises(ExceptionGroup):
        await inline_download._upload_resolved_medias(
            [
                ("https://scontent.test.cdninstagram.com/one.jpg", False),
                ("https://scontent.test.cdninstagram.com/two.jpg", False),
            ],
            {},
            MagicMock(),
        )

    good.__aexit__.assert_awaited_once()
    failed.__aexit__.assert_awaited_once()


def test_inline_dispatch_has_both_threads_hosts():
    assert inline_download._PLANS["threads.com"] == [inline_download._upload_threads]
    assert inline_download._PLANS["threads.net"] == [inline_download._upload_threads]


def test_download_domains_match_dispatch_keys():
    assert set(download_youtube._DOWNLOAD_DOMAINS) == set(
        download_youtube.DOWNLOAD_TYPE_MAP
    )
    assert download_youtube.DOWNLOAD_TYPE_MAP["threads.com"] == "threads"
    assert download_youtube.DOWNLOAD_TYPE_MAP["threads.net"] == "threads"

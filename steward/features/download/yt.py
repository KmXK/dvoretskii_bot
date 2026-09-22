import asyncio
import base64
import html as _html
import json
import logging
import os
import re
import tempfile
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
import yt_dlp
from aiohttp_socks import ProxyConnector
from pyrate_limiter import BucketFullException
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Message,
)
from yandex_music import Client as YandexMusicClient
from yandex_music.exceptions import YandexMusicError

from steward.data.repository import Repository
from steward.features.download import video_cache
from steward.features.download.callbacks import (
    download_file,
    download_and_send_medias,
    send_media_files,
)
from steward.features.transcribe import AutoVideoTranscriptionFeature
from steward.features.voice_video.transcription import create_transcription_reply
from steward.helpers.limiter import Duration, check_limit
from steward.helpers.media import has_audio_stream, is_video_file, run_ffmpeg

_TIKTOK_AUTO_LIMIT = "TIKTOK_AUTO_TRANSCRIBE"
_TIKTOK_AUTO_MAX_DURATION_SEC = 5 * 60

logger = logging.getLogger("download_controller")
yt_logger = logging.getLogger("youtube_dl")
yt_logger.setLevel(logging.DEBUG)

URL_REGEX = (
    r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
)

YT_LIMIT = "YT_LIMIT_OBJECT"

# Primary: только форматы БЕЗ ватермарки, h264 в приоритете
# (bytevc1/h265-гиры часто отдаются без аудиодорожки). Водяной
# download_addr сюда НЕ включаем. После закачки download_video_file
# пробит аудио ffprobe'ом и, если звука нет, перекачивает
# fallback'ом — водяным, но гарантированно озвученным.
TIKTOK_VIDEO_FORMAT = (
    "play_addr_h264/play_addr/play/"
    "bv*[vcodec*=h264]+ba/b[vcodec*=h264]/bv*+ba/b"
)
TIKTOK_FALLBACK_FORMAT = "download_addr/download/b"

_CAPTION_LIMIT = 950  # 1024 для caption минус накладные blockquote-тегов
_IMAGE_POST_CAPTION_LIMIT = 600
_AUDIO_SUFFIXES = frozenset({".aac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"})
_THREADS_HOSTS = frozenset({"threads.com", "threads.net"})
_THREADS_MEDIA_DOMAINS = ("cdninstagram.com", "fbcdn.net")
_THREADS_MEDIA_LIMIT = 20
_THREADS_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_THREADS_POST_PATH = re.compile(
    r"/(?:@[^/]+/)?(?:post|video|t)/(?P<shortcode>[^/?#&]+)",
    re.IGNORECASE,
)
_THREADS_SHARE_PATH = re.compile(r"/share/[^/?#&]+", re.IGNORECASE)
_THREADS_PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
}
THREADS_MEDIA_HEADERS = {
    **_THREADS_PAGE_HEADERS,
    "Referer": "https://www.threads.com/",
}


class YandexMusicDownloadError(RuntimeError):
    pass


def _auto_video_transcription_enabled(
    repository: Repository,
    message: Message,
    supported: bool,
) -> bool:
    return supported and repository.is_capability_enabled(
        message.chat_id,
        AutoVideoTranscriptionFeature,
    )


def _make_caption(info: Any, limit: int = _CAPTION_LIMIT) -> str | None:
    """Возвращает HTML-caption с описанием под expandable blockquote'ом.
    Шлите с parse_mode='HTML'."""
    if not isinstance(info, dict):
        return None
    raw = (
        info.get("description")
        or info.get("caption")
        or info.get("title")
        or ""
    ).strip()
    if not raw:
        return None
    if len(raw) > limit:
        raw = raw[: limit - 1].rstrip() + "…"
    from steward.helpers.formats import spoiler_block
    return spoiler_block(raw, header="Описание")


def _top_comments_html(info: Any, limit: int = 3) -> str | None:
    """Топ N комментариев по лайкам в expandable blockquote'е.
    yt-dlp заполняет info['comments'] только если getcomments=True; для
    некоторых платформ всё равно может вернуть пусто — это OK, возвращаем None."""
    if not isinstance(info, dict):
        return None
    comments = info.get("comments") or []
    if not isinstance(comments, list):
        return None
    # Только верхнеуровневые — без реплаев.
    flat = [c for c in comments if isinstance(c, dict) and not c.get("parent")]
    flat.sort(key=lambda c: (c.get("like_count") or 0), reverse=True)
    top = [c for c in flat if (c.get("like_count") or 0) > 0][:limit] or flat[:limit]
    if not top:
        return None

    lines: list[str] = []
    for i, c in enumerate(top, 1):
        author = (c.get("author") or c.get("author_id") or "—").strip()
        likes = c.get("like_count") or 0
        text = (c.get("text") or "").strip().replace("\n", " ")
        if len(text) > 200:
            text = text[:199].rstrip() + "…"
        if not text:
            continue
        lines.append(
            f"<b>{i}.</b> {_html.escape(author)} ❤️ {likes}\n{_html.escape(text)}"
        )
    if not lines:
        return None
    body = "\n\n".join(lines)
    return f"<blockquote expandable><b>Топ комментариев</b>\n{body}</blockquote>"


async def _auto_transcribe_short_video(
    repository: Repository,
    sent_video_msg: Message,
    filepath: str,
    info: Any,
    existing_caption_html: str = "",
) -> None:
    """Стримим расшифровку + саммари прямо в caption видео.
    Если в caption не влезает — `create_transcription_reply` сам падает в
    режим отдельного reply-сообщения. Плюс топ-3 комментариев отдельным reply."""
    try:
        await create_transcription_reply(
            repository,
            sent_video_msg,
            Path(filepath),
            speaker_user_id=None,
            speaker_username=None,
            speaker_fallback_name=None,
            speaker_first_name=None,
            caption_message=sent_video_msg,
            existing_caption_html=existing_caption_html,
        )
    except Exception as e:
        logger.warning("auto transcription for short tiktok failed: %s", e)

    top_html = _top_comments_html(info, 3)
    if top_html:
        try:
            await sent_video_msg.reply_html(top_html, disable_notification=True)
        except Exception as e:
            logger.warning("top comments send failed: %s", e)


async def _extract_info_only(url: str) -> Any:
    """yt_dlp в режиме «только метаданные» — без скачивания. Возвращает dict
    с описанием/тайтлом, либо None на ошибке."""
    def _run():
        try:
            return yt_dlp.YoutubeDL(
                {
                    "proxy": os.environ.get("DOWNLOAD_PROXY"),
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "logger": yt_logger,
                }  # type: ignore
            ).extract_info(url, download=False)
        except Exception as e:
            logger.warning("yt_dlp metadata extract failed for %s: %s", url, e)
            return None

    return await asyncio.to_thread(_run)

DOWNLOAD_TYPE_MAP = {
    "tiktok": "tiktok",
    "instagram.com": "reels",
    "threads.com": "threads",
    "threads.net": "threads",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "pinterest.com": "pinterest",
    "pin.it": "pinterest",
    "music.yandex": "music",
}

_DOWNLOAD_DOMAINS = {
    "tiktok": ("tiktok.com",),
    "instagram.com": ("instagram.com",),
    "threads.com": ("threads.com",),
    "threads.net": ("threads.net",),
    "youtube.com": ("youtube.com",),
    "youtu.be": ("youtu.be",),
    "pinterest.com": ("pinterest.com",),
    "pin.it": ("pin.it",),
    "music.yandex": ("music.yandex.ru",),
}


def find_download_urls(text: str) -> list[tuple[str, str]]:
    """Все поддерживаемые ссылки в тексте: список (url, dispatch_key).
    Единственное место, где текст матчится на загружаемые ссылки — им
    пользуются и чатовый DownloadFeature, и inline-режим. Ключ матчится
    по границам доменных меток: vm.tiktok.com и music.yandex.ru подходят,
    nottiktok.example.com — нет."""
    found: list[tuple[str, str]] = []
    for matched_url in re.findall(URL_REGEX, text):
        url = matched_url.rstrip(".,;:!?)]}>")
        host = urlparse(url).hostname
        for key, domains in _DOWNLOAD_DOMAINS.items():
            if _host_matches(host, domains):
                if key in _THREADS_HOSTS and not _is_threads_post_url(url):
                    break

                found.append((url, key))
                break
    return found


def _threads_shortcode(url: str) -> str | None:
    match = _THREADS_POST_PATH.search(urlparse(url).path)
    return match.group("shortcode") if match else None


def _host_matches(host: str | None, domains) -> bool:
    normalized = (host or "").lower().rstrip(".")
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in domains)


def _is_threads_post_url(url: str) -> bool:
    path = urlparse(url).path
    return _threads_shortcode(url) is not None or _THREADS_SHARE_PATH.search(path) is not None


class _ThreadsPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.json_scripts: list[str] = []
        self.meta: dict[str, str] = {}
        self._json_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta":
            key = values.get("property") or values.get("name")
            content = values.get("content")
            if key and content:
                self.meta[key] = content

        if tag == "script" and (values.get("type") or "").lower() == "application/json":
            self._json_parts = []

    def handle_data(self, data: str) -> None:
        if self._json_parts is not None:
            self._json_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._json_parts is not None:
            self.json_scripts.append("".join(self._json_parts))
            self._json_parts = None


def _find_threads_post(value: Any, shortcode: str) -> dict[str, Any] | None:
    stack = [value]
    fallback = None
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("code") == shortcode:
                fallback = item
                if item.get("carousel_media") or item.get("video_versions") or item.get("image_versions2"):
                    return item

            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)

    return fallback


def _threads_media_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    parsed = urlparse(value)
    if parsed.scheme != "https" or not _host_matches(parsed.hostname, _THREADS_MEDIA_DOMAINS):
        return None
    return value


def _best_threads_image(candidates: Any) -> str | None:
    if not isinstance(candidates, list):
        return None

    valid = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict) and _threads_media_url(candidate.get("url"))
    ]
    if not valid:
        return None

    best = max(
        valid,
        key=lambda candidate: (
            int(candidate.get("width") or 0) * int(candidate.get("height") or 0),
            int(candidate.get("width") or 0),
        ),
    )
    return best["url"]


def _best_threads_video(versions: Any) -> str | None:
    if not isinstance(versions, list):
        return None

    valid = [
        version
        for version in versions
        if isinstance(version, dict) and _threads_media_url(version.get("url"))
    ]
    if not valid:
        return None

    best = max(
        valid,
        key=lambda version: (
            int(version.get("width") or 0) * int(version.get("height") or 0),
            int(version.get("bitrate") or 0),
        ),
    )
    return best["url"]


def _threads_post_medias(post: dict[str, Any]) -> list[tuple[str, bool]]:
    media_items = post.get("carousel_media") or [post]
    medias: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for media in media_items:
        if not isinstance(media, dict):
            continue

        video_url = _best_threads_video(media.get("video_versions"))
        media_url = video_url or _best_threads_image(
            (media.get("image_versions2") or {}).get("candidates")
        )
        if not media_url or media_url in seen:
            continue

        seen.add(media_url)
        medias.append((media_url, video_url is not None))
        if len(medias) == _THREADS_MEDIA_LIMIT:
            break

    return medias


def parse_threads_page(
    page: str,
    final_url: str,
    source_url: str,
) -> tuple[list[tuple[str, bool]], dict[str, Any]]:
    parser = _ThreadsPageParser()
    parser.feed(page)

    canonical_url = parser.meta.get("og:url") or ""
    shortcode = (
        _threads_shortcode(final_url)
        or _threads_shortcode(canonical_url)
        or _threads_shortcode(source_url)
    )
    if not shortcode:
        raise ValueError("не удалось определить пост Threads")

    post = None
    medias = []
    matched_post = False
    for script in parser.json_scripts:
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue

        candidate = _find_threads_post(data, shortcode)
        if not candidate:
            continue

        matched_post = True
        candidate_medias = _threads_post_medias(candidate)
        if candidate_medias:
            post = candidate
            medias = candidate_medias
            break

    if not post:
        if matched_post:
            raise ValueError("в посте Threads нет доступных фото или видео")

        raise ValueError("Threads не отдал данные поста")

    user = post.get("user") or {}
    caption = post.get("caption") or {}
    description = caption.get("text") if isinstance(caption, dict) else None
    description = description or parser.meta.get("og:description") or ""
    username = user.get("username") if isinstance(user, dict) else None
    return medias, {
        "description": description,
        "title": description or (f"Threads @{username}" if username else "Threads"),
        "uploader": username,
    }


async def _fetch_threads_page(url: str) -> tuple[str, str]:
    if not _host_matches(urlparse(url).hostname, _THREADS_HOSTS):
        raise ValueError("неподдерживаемый адрес Threads")

    connector = None
    if proxy := os.environ.get("DOWNLOAD_PROXY"):
        connector = ProxyConnector.from_url(proxy)

    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=_THREADS_PAGE_HEADERS,
    ) as session:
        current_url = url
        for _ in range(6):
            if not _host_matches(urlparse(current_url).hostname, _THREADS_HOSTS):
                raise ValueError("Threads перенаправил на неподдерживаемый адрес")

            async with session.get(current_url, allow_redirects=False) as response:
                if response.status in _THREADS_REDIRECT_STATUSES:
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Threads вернул перенаправление без адреса")
                    current_url = urljoin(current_url, location)
                    continue

                response.raise_for_status()
                return await response.text(), current_url

        raise ValueError("слишком много перенаправлений Threads")


async def resolve_threads_medias(
    url: str,
) -> tuple[list[tuple[str, bool]], dict[str, Any]]:
    page, final_url = await _fetch_threads_page(url)
    return parse_threads_page(
        page,
        final_url,
        url,
    )


async def load_threads(repository: Repository, url: str, message: Message) -> None:
    medias, metadata = await resolve_threads_medias(url)
    await download_and_send_medias(
        repository,
        message,
        medias,
        use_proxy=True,
        caption=_make_caption(metadata, _IMAGE_POST_CAPTION_LIMIT),
        describe_images=True,
        request_headers=THREADS_MEDIA_HEADERS,
        transcription_enabled=False,
    )


async def resolve_instagram_medias(url: str) -> list[tuple[str, bool]]:
    """Список (media_url, is_video) поста инсты через igdl-прокси."""
    proxy_url = f"https://download.proxy.nigger.by/igdl?url={url}"

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(connect=2)
    ) as session:
        async with session.get(proxy_url) as response:
            if response.status != 200:
                raise Exception(f"invalid response: {response}")
            json_resp = await response.json()

    medias: list[tuple[str, bool]] = []
    for x in json_resp["url"]["data"]:
        media_url = x["url"]
        token = parse_qs(urlparse(media_url).query)["token"][0]
        payload = token.split(".")[1]
        json_data = base64.urlsafe_b64decode(
            payload + ("=" * (4 - (len(payload) % 4)))
        )
        filename = json.loads(json_data)["filename"]
        medias.append((media_url, filename.endswith("mp4")))

    return sorted(set(medias), key=lambda x: medias.index(x))


async def load_instagram(repository: Repository, url: str, message: Message) -> None:
    meta_task = asyncio.create_task(_extract_info_only(url))

    try:
        medias = await resolve_instagram_medias(url)
    except BaseException:
        meta_task.cancel()
        raise

    if len(medias) == 0:
        meta_task.cancel()
        return

    caption = None
    try:
        info = await meta_task
        caption = _make_caption(info, _IMAGE_POST_CAPTION_LIMIT)
    except Exception as e:
        logger.warning("instagram description fetch failed: %s", e)
    await download_and_send_medias(
        repository,
        message,
        medias,
        use_proxy=True,
        caption=caption,
        describe_images=True,
    )


async def download_yandex_audio(url: str, dir: str) -> str:
    """Качает трек Яндекс.Музыки в `dir`, возвращает путь к файлу."""
    token = os.environ.get("YANDEX_MUSIC_TOKEN")
    if not token:
        raise YandexMusicDownloadError("Яндекс Музыка не настроена: нужен OAuth-токен")

    match = re.search(r"/track/(\d+)", urlparse(url).path)
    if match is None:
        raise YandexMusicDownloadError("Не удалось определить трек в ссылке")

    track_id = match.group(1)
    filepath = os.path.join(dir, "track.mp3")

    def _run() -> None:
        try:
            client = YandexMusicClient(token).init()
            tracks = client.tracks([track_id])
            if not tracks:
                raise YandexMusicDownloadError("Яндекс Музыка не нашла трек")

            download_infos = [
                info
                for info in tracks[0].get_download_info()
                if info.codec == "mp3" and not info.preview
            ]
            if not download_infos:
                raise YandexMusicDownloadError(
                    "Аккаунт Яндекс Музыки не даёт скачать полный трек"
                )

            max(download_infos, key=lambda info: info.bitrate_in_kbps).download(filepath)
        except YandexMusicError as error:
            raise YandexMusicDownloadError(
                "Яндекс Музыка не отдала трек: проверь токен и подписку"
            ) from error

    logger.info("Downloading Yandex Music track %s", track_id)
    await asyncio.to_thread(_run)
    if not os.path.isfile(filepath) or os.path.getsize(filepath) == 0:
        raise YandexMusicDownloadError("Яндекс Музыка вернула пустой файл")

    return filepath


async def load_yandex_music(_repository: Repository, url: str, message: Message) -> None:
    with tempfile.TemporaryDirectory(prefix="ym_") as dir:
        try:
            filepath = await download_yandex_audio(url, dir)
        except YandexMusicDownloadError as error:
            logger.warning("Yandex Music download failed: %s", error)
            await message.reply_text(str(error))
            return

        with open(filepath, "rb") as file:
            logger.info(file)
            await message.reply_audio(file, filename=file.name)


async def download_video_file(
    url: str,
    dir: str,
    *,
    type_name: str = "video",
    cookie_file: str | None = None,
    video_format: str = "(bv+ba)/best",
    fallback_format: str | None = None,
    get_comments: bool = False,
) -> tuple[Any, str]:
    """Качает видео в `dir` через yt-dlp, возвращает (info, путь к файлу)."""
    base_opts: dict[str, Any] = {
        "proxy": os.environ.get("DOWNLOAD_PROXY"),
        "verbose": True,
        "outtmpl": dir + "/file",
        "logger": yt_logger,
        "cookiefile": cookie_file,
        "format_sort": ["ext:mp4", "res:1080"],
        "max_filesize": 250 * 1024 * 1024,
    }
    if get_comments:
        base_opts["getcomments"] = True

    def _download(fmt: str) -> tuple[Any, str]:
        # Чистим каталог, чтобы повторная закачка не подхватила
        # файл от предыдущей попытки.
        for f in os.listdir(dir):
            os.remove(os.path.join(dir, f))
        opts = {**base_opts, "format": fmt}
        info = yt_dlp.YoutubeDL(opts).extract_info(url)  # type: ignore
        files = os.listdir(dir)
        logging.info(files)
        return info, dir + "/" + files[0]

    info, filepath = await asyncio.to_thread(_download, video_format)

    # Водяная версия (download_addr) — последний резерв: некоторые
    # форматы без ватермарки помечены acodec=aac, но физически немые.
    # Если в скачанном файле нет реальной аудиодорожки — перекачиваем
    # гарантированно озвученным (но водяным) форматом.
    if fallback_format and not await has_audio_stream(Path(filepath)):
        logger.info(
            "%s: no audio stream in no-watermark file, "
            "retrying with watermarked fallback",
            type_name,
        )
        info, filepath = await asyncio.to_thread(_download, fallback_format)

    return info, filepath


def _get_gallery_audio_url(metadata: Any) -> str | None:
    if not isinstance(metadata, dict):
        return None

    video = metadata.get("video")
    if isinstance(video, dict):
        audio_infos = video.get("bitrateAudioInfo") or []
        if isinstance(audio_infos, dict):
            audio_infos = [audio_infos]

        for audio_info in audio_infos:
            if not isinstance(audio_info, dict):
                continue

            urls = audio_info.get("UrlList")
            if not isinstance(urls, dict):
                continue

            for key in ("MainUrl", "BackupUrl", "FallbackUrl"):
                audio_url = urls.get(key)
                if audio_url:
                    return audio_url

    music = metadata.get("music")
    if isinstance(music, dict):
        return music.get("playUrl") or None

    return None


def _gallery_audio_filename(metadata: Any, audio_path: str | Path) -> str:
    suffix = Path(audio_path).suffix.lower()
    if suffix not in _AUDIO_SUFFIXES:
        suffix = ".mp3"
    if not isinstance(metadata, dict):
        return f"Audio{suffix}"

    music = metadata.get("music")
    if not isinstance(music, dict):
        music = {}
    title = (
        music.get("title")
        or music.get("musicName")
        or music.get("matchedPGCSoundTitle")
        or metadata.get("audio_title")
        or metadata.get("track_title")
    )
    artist = (
        music.get("authorName")
        or music.get("author")
        or metadata.get("artist")
        or metadata.get("uploader")
    )
    if not title:
        return f"Audio{suffix}"

    display = str(title).strip()
    if artist:
        artist_name = str(artist).strip()
        if artist_name and artist_name.lower() not in display.lower():
            display = f"{display} — {artist_name}"
    display = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", display)
    display = " ".join(display.split()).strip(" .")
    if not display:
        return f"Audio{suffix}"
    if len(display) > 72:
        display = display[:72].rstrip()
    return f"{display}{suffix}"


def make_video_loader(
    type_name: str,
    cookie_file: str | None = None,
    pre_call: Callable[[], Any] = lambda: None,
    auto_transcribe_short: bool = False,
    video_format: str = "(bv+ba)/best",
    fallback_format: str | None = None,
):
    async def wrapper(repository: Repository, url: str, message: Message) -> None:
        pre_call()

        auto_transcription_enabled = _auto_video_transcription_enabled(
            repository,
            message,
            auto_transcribe_short,
        )

        logger.info(f"trying get video from {type_name}...")

        with tempfile.TemporaryDirectory(prefix=f"{type_name}_") as dir:
            info, filepath = await download_video_file(
                url,
                dir,
                type_name=type_name,
                cookie_file=cookie_file,
                video_format=video_format,
                fallback_format=fallback_format,
                get_comments=auto_transcription_enabled,
            )

            width: Any = None
            height: Any = None
            if isinstance(info, dict):
                width = info.get("width", 0)
                height = info.get("height", 0)

            duration = info.get("duration") if isinstance(info, dict) else None

            will_auto_transcribe = False
            if (
                auto_transcription_enabled
                and duration is not None
                and duration < _TIKTOK_AUTO_MAX_DURATION_SEC
            ):
                try:
                    check_limit(_TIKTOK_AUTO_LIMIT, 2, Duration.MINUTE)
                    will_auto_transcribe = True
                except BucketFullException:
                    logger.info("auto-transcribe rate-limited for %s", type_name)

            reply_markup = None
            if (
                not will_auto_transcribe
                and duration is not None
                and duration < 3 * 60
            ):
                link_id = uuid.uuid4().hex
                repository.db.saved_links.add(link_id, url)
                await repository.save()
                reply_markup = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Текст",
                                callback_data=f"download:trans|{link_id}",
                            ),
                        ],
                    ]
                )

            caption = _make_caption(info)

            with open(filepath, "rb") as file:
                sent_video = await message.reply_video(
                    InputFile(file, filename=f"{type_name} Video"),
                    supports_streaming=True,
                    width=int(width) if width is not None else None,
                    height=int(height) if height is not None else None,
                    reply_markup=reply_markup,
                    caption=caption,
                    parse_mode="HTML" if caption else None,
                )

            if sent_video is not None and sent_video.video is not None:
                video_cache.put(
                    url,
                    [video_cache.CachedMedia(
                        file_id=sent_video.video.file_id,
                        caption=caption,
                        duration=float(duration) if duration else None,
                    )],
                )

            logger.info(f"video {type_name} downloaded successfully")

            if will_auto_transcribe and sent_video is not None:
                await _auto_transcribe_short_video(
                    repository, sent_video, filepath, info, caption or ""
                )

    return wrapper


async def download_image_files(
    url: str,
    dir: str,
    cookie_file: str | None = None,
) -> tuple[list[str], list[str], dict[str, Any] | None]:
    """Качает медиа поста через gallery-dl в `dir`.
    Возвращает (медиа, аудио, metadata)."""
    args: list[str] = []
    if os.environ.get("DOWNLOAD_PROXY"):
        args += ["--proxy", os.environ.get("DOWNLOAD_PROXY") or ""]
    args += [
        "--verbose",
        "--write-metadata",
        "-f",
        "{num}.{extension}",
        "-D",
        dir,
    ]
    if cookie_file:
        args += ["-C", cookie_file]
    args.append(url)

    process = await asyncio.create_subprocess_exec(
        "gallery-dl",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    logger.info(
        "gallery-dl process done: stdout=%s, stderr=%s",
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )

    if process.returncode != 0:
        raise Exception(f"gallery-dl exited with error {process.returncode}")

    all_files = [
        os.path.join(dir, x)
        for x in sorted(
            (x for x in os.listdir(dir) if not x.endswith(".json")),
            key=lambda x: f"{int(x.split('.')[0]):03d}",
        )
    ]

    metadata = None
    for media_path in all_files:
        metadata_path = media_path + ".json"
        if not os.path.exists(metadata_path):
            continue
        try:
            with open(metadata_path) as file:
                loaded = json.load(file)
            if isinstance(loaded, dict):
                metadata = loaded
                break
        except Exception as error:
            logger.warning("gallery metadata read failed %s: %s", metadata_path, error)

    for media_path in all_files:
        metadata_path = media_path + ".json"
        if not is_video_file(media_path) or not os.path.exists(metadata_path):
            continue

        if await has_audio_stream(Path(media_path)):
            continue

        with open(metadata_path) as file:
            media_metadata = json.load(file)

        audio_url = _get_gallery_audio_url(media_metadata)
        if not audio_url:
            continue

        audio_path = media_path + ".audio"
        async with download_file(audio_url, use_proxy=True) as audio_file:
            with open(audio_path, "wb") as output:
                while chunk := audio_file.read(1024 * 1024):
                    output.write(chunk)

        merged_path = media_path + ".merged.mp4"
        await run_ffmpeg(
            "-i",
            media_path,
            "-i",
            audio_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            merged_path,
        )
        os.replace(merged_path, media_path)
        os.remove(audio_path)
        logger.info("Добавлена аудиодорожка в %s", media_path)

    images = [x for x in all_files if Path(x).suffix.lower() not in _AUDIO_SUFFIXES]
    audios = [x for x in all_files if Path(x).suffix.lower() in _AUDIO_SUFFIXES]
    return images, audios, metadata


def make_images_loader(
    type_name: str,
    cookie_file: str | None = None,
):
    async def wrapper(_repository: Repository, url: str, message: Message) -> None:
        logger.info(f"trying get images from {type_name}...")

        with tempfile.TemporaryDirectory(prefix=f"{type_name}_") as dir:
            images, audios, metadata = await download_image_files(
                url,
                dir,
                cookie_file,
            )

            await send_media_files(
                message,
                images,
                caption=_make_caption(metadata, _IMAGE_POST_CAPTION_LIMIT),
                describe_images=True,
            )

            if len(audios) > 0:
                with open(audios[0], "rb") as file:
                    await message.reply_audio(
                        file,
                        filename=_gallery_audio_filename(metadata, audios[0]),
                    )

    return wrapper


def build_dispatch(repository: Repository) -> dict[str, list]:
    yt_pre = lambda: check_limit(YT_LIMIT, 1, 10 * Duration.SECOND)

    def _bind(loader):
        async def runner(url, message):
            await loader(repository, url, message)
        return runner

    return {
        "tiktok": [
            _bind(make_video_loader(
                "tiktok",
                auto_transcribe_short=True,
                video_format=TIKTOK_VIDEO_FORMAT,
                fallback_format=TIKTOK_FALLBACK_FORMAT,
            )),
            _bind(make_images_loader("tiktok")),
        ],
        "instagram.com": [
            lambda url, message: load_instagram(repository, url, message),
        ],
        "threads.com": [
            lambda url, message: load_threads(repository, url, message),
        ],
        "threads.net": [
            lambda url, message: load_threads(repository, url, message),
        ],
        "youtube.com": [_bind(make_video_loader("youtube", pre_call=yt_pre))],
        "youtu.be": [_bind(make_video_loader("youtube", pre_call=yt_pre))],
        "pinterest.com": [
            _bind(make_video_loader("pinterest")),
            _bind(make_images_loader("pinterest")),
        ],
        "pin.it": [
            _bind(make_video_loader("pinterest")),
            _bind(make_images_loader("pinterest")),
        ],
        "music.yandex": [
            lambda url, message: load_yandex_music(repository, url, message),
        ],
    }

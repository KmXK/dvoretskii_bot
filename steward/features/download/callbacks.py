import asyncio
import logging
import os
import tempfile
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path

import aiohttp
from aiohttp_socks import ProxyConnector
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from steward.data.repository import Repository
from steward.features.download.image_description import (
    append_image_description,
    describe_image_files,
)
from steward.helpers import morphy
from steward.helpers.media import is_video_file

logger = logging.getLogger("download_controller")

REMOTE_MEDIA_FILE_LIMIT = 250 * 1024 * 1024
REMOTE_MEDIA_TOTAL_LIMIT = 500 * 1024 * 1024
REMOTE_MEDIA_CONCURRENCY = 3


class DownloadBudget:
    def __init__(self, max_bytes: int):
        self._remaining = max_bytes
        self._lock = asyncio.Lock()

    async def consume(self, size: int) -> None:
        async with self._lock:
            if size > self._remaining:
                raise ValueError("общий размер медиа превышает допустимый лимит")
            self._remaining -= size


@asynccontextmanager
async def download_file(
    url: str,
    use_proxy: bool = False,
    request_headers: dict[str, str] | None = None,
    max_bytes: int = REMOTE_MEDIA_FILE_LIMIT,
    budget: DownloadBudget | None = None,
):
    logger.info(f"Скачиваем файл: {url}")
    with tempfile.NamedTemporaryFile("r+b") as file:
        logger.info(f"Создан файл {file.name}")

        connector = None
        if use_proxy and os.environ.get("DOWNLOAD_PROXY"):
            connector = ProxyConnector.from_url(
                os.environ.get("DOWNLOAD_PROXY") or ""
            )

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(
                total=180,
                connect=10,
                sock_read=30,
            ),
        ) as session:
            async with session.get(url, headers=request_headers) as response:
                response.raise_for_status()
                content_length = response.content_length
                if content_length is not None and content_length > max_bytes:
                    raise ValueError("размер файла превышает допустимый лимит")

                downloaded = 0
                while True:
                    chunk = await response.content.readany()
                    if not chunk:
                        break

                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise ValueError("размер файла превышает допустимый лимит")
                    if budget is not None:
                        await budget.consume(len(chunk))

                    file.write(chunk)

        logger.info("Файл был скачен")
        file.seek(0)

        try:
            yield file
        except Exception as e:
            logger.exception(e)
            raise


def _build_trans_markup(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Текст", callback_data=callback_data)]]
    )


def _media_group_chunks(medias: list) -> list[list]:
    chunks = [medias[index : index + 10] for index in range(0, len(medias), 10)]
    if len(chunks) > 1 and len(chunks[-1]) == 1:
        chunks[-1].insert(0, chunks[-2].pop())
    return chunks


async def enter_download_contexts(
    contexts: list,
    max_concurrency: int = REMOTE_MEDIA_CONCURRENCY,
) -> list:
    if not contexts:
        return []

    semaphore = asyncio.Semaphore(max_concurrency)

    async def enter(context):
        async with semaphore:
            return await context.__aenter__()

    return await asyncio.gather(
        *[enter(context) for context in contexts],
        return_exceptions=True,
    )


async def download_and_send_medias(
    repository: Repository,
    message: Message,
    videos_or_images: list[tuple[str, bool]],
    retries_count: int = 5,
    use_proxy: bool = False,
    caption: str | None = None,
    describe_images: bool = False,
    request_headers: dict[str, str] | None = None,
    transcription_enabled: bool = True,
):
    import uuid

    logger.info(
        f"Отправляется {morphy.make_agree_with_number('картинка', len(videos_or_images))}"
    )

    budget = DownloadBudget(REMOTE_MEDIA_TOTAL_LIMIT)
    files_tasks = [
        download_file(
            url,
            use_proxy=use_proxy,
            request_headers=request_headers,
            budget=budget,
        )
        for url, _ in videos_or_images
    ]

    try:
        results = await enter_download_contexts(
            files_tasks,
        )

        logger.info(results)

        exceptions = [exc for exc in results if isinstance(exc, Exception)]
        if len(exceptions) > 0:
            raise ExceptionGroup("", exceptions)  # noqa: F821

        if describe_images:
            image_paths = [
                Path(file.name)
                for index, file in enumerate(results)
                if not isinstance(file, BaseException)
                and not videos_or_images[index][1]
            ]
            description = await describe_image_files(image_paths)
            caption = append_image_description(caption, description)

        medias = [
            InputMediaPhoto(
                file,
                caption=caption if i == 0 else None,
                parse_mode="HTML" if i == 0 and caption else None,
            )
            if not videos_or_images[i][1]
            else InputMediaVideo(
                file,
                supports_streaming=True,
                caption=caption if i == 0 else None,
                parse_mode="HTML" if i == 0 and caption else None,
            )
            for i, file in enumerate(results)
            if not isinstance(file, BaseException)
        ]

        reply_markup = None
        if len(videos_or_images) == 1:
            assert not isinstance(results[0], BaseException)
            results[0].seek(0)
            if videos_or_images[0][1]:
                if transcription_enabled:
                    link_id = uuid.uuid4().hex
                    repository.db.saved_links.add(link_id, videos_or_images[0][0])
                    await repository.save()
                    reply_markup = _build_trans_markup(
                        f"download:trans|no_ydl_{link_id}"
                    )

                await message.reply_video(
                    results[0],
                    supports_streaming=True,
                    disable_notification=True,
                    reply_markup=reply_markup,
                    caption=caption,
                    parse_mode="HTML" if caption else None,
                )
            else:
                await message.reply_photo(
                    results[0],
                    disable_notification=True,
                    caption=caption,
                    parse_mode="HTML" if caption else None,
                )
        else:
            media_groups = _media_group_chunks(medias)
            for index, media_group in enumerate(media_groups):
                retry = 0
                while retry < retries_count:
                    try:
                        await message.reply_media_group(
                            media_group,
                            disable_notification=True,
                        )
                        break
                    except Exception as e:
                        logging.exception(e)
                        await asyncio.sleep(5)
                        retry += 1

                if index + 1 < len(media_groups):
                    await asyncio.sleep(2)

        logger.info("Картинки отправлены")

    finally:
        await asyncio.gather(
            *[
                task.__aexit__(None, None, None)
                for task in files_tasks
            ],
            return_exceptions=True,
        )


async def send_media_files(
    message: Message,
    media_paths: list[str],
    retries_count: int = 5,
    caption: str | None = None,
    describe_images: bool = False,
):
    logger.info("Отправляется медиа: %s", len(media_paths))

    if describe_images:
        image_paths = [
            Path(media_path)
            for media_path in media_paths
            if not is_video_file(media_path)
        ]
        description = await describe_image_files(image_paths)
        caption = append_image_description(caption, description)

    if len(media_paths) == 1:
        with open(media_paths[0], "rb") as file:
            if is_video_file(media_paths[0]):
                await message.reply_video(
                    file,
                    supports_streaming=True,
                    disable_notification=True,
                    caption=caption,
                    parse_mode="HTML" if caption else None,
                )
            else:
                await message.reply_photo(
                    file,
                    disable_notification=True,
                    caption=caption,
                    parse_mode="HTML" if caption else None,
                )

        logger.info("Медиа отправлено")
        return

    medias: list[InputMediaPhoto | InputMediaVideo] = []

    with ExitStack() as stack:
        for index, media_path in enumerate(media_paths):
            file = stack.enter_context(open(media_path, "rb"))
            if is_video_file(media_path):
                media = InputMediaVideo(
                    file,
                    supports_streaming=True,
                    caption=caption if index == 0 else None,
                    parse_mode="HTML" if index == 0 and caption else None,
                )
            else:
                media = InputMediaPhoto(
                    file,
                    caption=caption if index == 0 else None,
                    parse_mode="HTML" if index == 0 and caption else None,
                )

            medias.append(media)

        media_groups = _media_group_chunks(medias)
        for index, media_group in enumerate(media_groups):
            retry = 0
            while retry < retries_count:
                try:
                    await message.reply_media_group(
                        media_group,
                        disable_notification=True,
                    )
                    break
                except Exception as e:
                    logging.exception(e)
                    await asyncio.sleep(5)
                    retry += 1

            if index + 1 < len(media_groups):
                await asyncio.sleep(2)

    logger.info("Медиа отправлены")

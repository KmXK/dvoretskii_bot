import asyncio
import logging
import os
import tempfile
from contextlib import ExitStack, asynccontextmanager

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
from steward.helpers import morphy

logger = logging.getLogger("download_controller")


@asynccontextmanager
async def download_file(url: str, use_proxy: bool = False):
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
            timeout=aiohttp.ClientTimeout(connect=2),
        ) as session:
            async with session.get(url) as response:
                while True:
                    chunk = await response.content.readany()
                    if not chunk:
                        break
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


async def download_and_send_medias(
    repository: Repository,
    message: Message,
    videos_or_images: list[tuple[str, bool]],
    retries_count: int = 5,
    use_proxy: bool = False,
):
    import uuid

    logger.info(
        f"Отправляется {morphy.make_agree_with_number('картинка', len(videos_or_images))}"
    )

    files_tasks = [
        download_file(url, use_proxy=use_proxy) for url, _ in videos_or_images
    ]

    try:
        results = await asyncio.gather(
            *[task.__aenter__() for task in files_tasks],
            return_exceptions=True,
        )

        logger.info(results)

        exceptions = [exc for exc in results if isinstance(exc, Exception)]
        if len(exceptions) > 0:
            raise ExceptionGroup("", exceptions)  # noqa: F821

        medias = [
            InputMediaPhoto(file)
            if not videos_or_images[i][1]
            else InputMediaVideo(file)
            for i, file in enumerate(results)
            if not isinstance(file, BaseException)
        ]

        reply_markup = None
        if len(videos_or_images) == 1 and videos_or_images[0][1]:
            assert not isinstance(results[0], BaseException)
            results[0].seek(0)

            link_id = uuid.uuid4().hex
            repository.db.saved_links.add(link_id, videos_or_images[0][0])
            await repository.save()
            reply_markup = _build_trans_markup(
                f"download:trans|no_ydl_{link_id}"
            )
            await message.reply_video(
                results[0],
                disable_notification=True,
                reply_markup=reply_markup,
            )
        else:
            for i in range(0, len(medias), 10):
                retry = 0
                while retry < retries_count:
                    try:
                        await message.reply_media_group(
                            medias[i : i + 10],
                            disable_notification=True,
                        )
                        break
                    except Exception as e:
                        logging.exception(e)
                        await asyncio.sleep(5)
                        retry += 1

                if i + 10 < len(medias):
                    await asyncio.sleep(2)

        logger.info("Картинки отправлены")

    except Exception:
        for task in files_tasks:
            await task.__aexit__(None, None, None)
        raise


async def send_images(
    message: Message,
    images: list[str],
    retries_count: int = 5,
):
    logger.info(
        f"Отправляется {morphy.make_agree_with_number('картинка', len(images))}"
    )

    medias: list[InputMediaPhoto] = []

    with ExitStack() as stack:
        for image_path in images:
            file = stack.enter_context(open(image_path, "rb"))
            medias.append(InputMediaPhoto(file))

        for i in range(0, len(medias), 10):
            retry = 0
            while retry < retries_count:
                try:
                    await message.reply_media_group(
                        medias[i : i + 10],
                        disable_notification=True,
                    )
                    break
                except Exception as e:
                    logging.exception(e)
                    await asyncio.sleep(5)
                    retry += 1

            if i + 10 < len(images):
                await asyncio.sleep(2)

    logger.info("Картинки отправлены")

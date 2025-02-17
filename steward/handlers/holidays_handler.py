import logging
from asyncio import Lock
from dataclasses import dataclass
from datetime import date
from os import environ

from aiohttp import ClientSession
from bs4 import BeautifulSoup

from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.formats import format_lined_list

logger = logging.getLogger(__name__)

url = "https://kakoysegodnyaprazdnik.ru/"

@dataclass
class Cache:
    holidays: list[tuple[int, str]]
    date: date

cache = Cache([], date.fromtimestamp(0))
mutex = Lock()

@CommandHandler("holidays", only_admin=False)
class HolidaysHandler(Handler):
    async def chat(self, update, context):
        assert update.message and update.message.text

        if cloud_flare_port := environ.get("CLOUDFLARE_BYPASS_PORT"):
            target_url = 'http://localhost:%s/html?url=%s' % (cloud_flare_port, url)
        else:
            target_url = url

        # TODO: cache logic in separate class
        async with mutex:
            if cache.date != date.today():
                async with ClientSession() as session:
                    response = await session.get(target_url)

                    logging.info(response)
                    content = await response.text()

                    # redirect is also error here
                    if response.status >= 300:
                        logger.warning(
                            f"Failed to get holidays: {response.status} {content}"
                        )
                        await update.message.reply_text("На этом мои полномочия все(")
                        return True

                soup = BeautifulSoup(content, "html.parser")

                cache.date = date.today()

                def get_holiday_name(container):
                    lifetime = container.select_one('span.super')
                    name = container.select_one('span[itemprop="text"]').text
                    return name + (f" ({lifetime.text})" if lifetime else "")

                cache.holidays = [
                    (i + 1, get_holiday_name(container))
                    for i, container in enumerate(
                        soup.select(
                            'div[itemtype="http://schema.org/Answer"]'
                        )
                    )
                ]

            holidays = cache.holidays

        await update.message.reply_markdown(
            "\n".join([
                "Праздники сегодня:",
                format_lined_list(holidays),
            ])
        )
        return True

    def help(self):
        return "/holidays - узнать какие сегодня праздники"

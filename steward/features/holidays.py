import logging
from asyncio import Lock
from dataclasses import dataclass
from datetime import date
from os import environ

from aiohttp import ClientSession
from bs4 import BeautifulSoup

from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.formats import format_lined_list

logger = logging.getLogger(__name__)

_URL = "https://kakoysegodnyaprazdnik.ru/"


@dataclass
class _Cache:
    holidays: list[tuple[int, str]]
    date: date


_cache = _Cache([], date.fromtimestamp(0))
_mutex = Lock()


class HolidaysFeature(Feature):
    command = "holidays"
    description = "Какие сегодня праздники"

    @subcommand("", description="Праздники сегодня")
    async def show(self, ctx: FeatureContext):
        cf_port = environ.get("CLOUDFLARE_BYPASS_PORT")
        target_url = (
            f"http://localhost:{cf_port}/html?url={_URL}" if cf_port else _URL
        )
        async with _mutex:
            if _cache.date != date.today():
                async with ClientSession() as session:
                    response = await session.get(target_url)
                    content = await response.text()
                    if response.status >= 300:
                        logger.warning("Failed to get holidays: %s", response.status)
                        await ctx.reply("На этом мои полномочия все(")
                        return
                soup = BeautifulSoup(content, "html.parser")
                _cache.date = date.today()

                def get_name(container):
                    lifetime = container.select_one("span.super")
                    name = container.select_one('span[itemprop="text"]').text
                    return name + (f" ({lifetime.text})" if lifetime else "")

                _cache.holidays = [
                    (i + 1, get_name(c))
                    for i, c in enumerate(
                        soup.select('div[itemtype="http://schema.org/Answer"]')
                    )
                ]
            holidays = list(_cache.holidays)
        await ctx.reply(
            "\n".join(["Праздники сегодня:", format_lined_list(holidays)])
        )

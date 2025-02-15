import logging

from aiohttp import ClientSession
from bs4 import BeautifulSoup

from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.formats import format_lined_list

logger = logging.getLogger(__name__)

url = "https://kakoysegodnyaprazdnik.ru/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
}


@CommandHandler("holidays", only_admin=False)
class HolidaysHandler(Handler):
    async def chat(self, update, context):
        assert update.message and update.message.text

        async with ClientSession() as session:
            response = await session.get(url, headers=headers)

        content = await response.text()

        # redirect is also error here
        if response.status >= 300:
            logger.warning(f"Failed to get holidays: {response.status} {content}")
            await update.message.reply_text("На этом мои полномочия все(")
            return True

        soup = BeautifulSoup(content, "html.parser")

        holidays = [
            (i + 1, span.text)
            for i, span in enumerate(
                soup.select(
                    'div[itemtype="http://schema.org/Answer"] span[itemprop="text"]'
                )
            )
        ]

        await update.message.reply_markdown(
            "\n".join([
                "Праздники сегодня:",
                format_lined_list(holidays),
            ])
        )
        return True

    def help(self):
        return "/holidays - узнать какие сегодня праздники"

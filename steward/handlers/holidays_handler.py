import logging

import cloudscraper
from bs4 import BeautifulSoup

from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.formats import format_lined_list

logger = logging.getLogger(__name__)

url = "https://kakoysegodnyaprazdnik.ru/"


@CommandHandler("holidays", only_admin=False)
class HolidaysHandler(Handler):
    async def chat(self, update, context):
        assert update.message and update.message.text

        scaper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )

        response = scaper.get(url)

        # redirect is also error here
        if response.status_code >= 300:
            logger.warning(
                f"Failed to get holidays: {response.status_code} {response.text}"
            )
            await update.message.reply_text("На этом мои полномочия все(")
            return True

        soup = BeautifulSoup(response.text, "html.parser")

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

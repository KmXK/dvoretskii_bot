import logging
import cloudscraper

from aiohttp import ClientSession
from bs4 import BeautifulSoup

from steward.handlers.handler import Handler, validate_command_msg

logger = logging.getLogger(__name__)

url = 'https://kakoysegodnyaprazdnik.ru/'
headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ru,en-US;q=0.9,en;q=0.8',
    }

cookies = {
        'PHPSESSID': '***REMOVED***',
        '5eacd459ffc899eab97276533bb38fbc': 'FuckYouMudila',
    }

class HolidaysHandler(Handler):
    async def chat(self, update, context):
        assert update.message and update.message.text
        if not validate_command_msg(update, ["holidays"]):
            return False

        logger.info(f"using endpoint: {url}")
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, headers=headers, cookies=cookies)
        
        if response.status_code != 200:
            await update.message.reply_text(
                f"На этом мои полномочия все("
            )
            return True
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        holidays = [
            f"`{i + 1}.` {block.find('span', itemprop='text').text.strip().replace('`', '\\`')} ({block.find('span', class_='super').text.strip()})"
            if block.find('span', class_='super')
            else f"`{i + 1}.` {block.find('span', itemprop='text').text.strip().replace('`', '\\`')}"
            for i, block in enumerate(soup.find_all('div', itemprop='suggestedAnswer'))
        ]

        await update.message.reply_markdown(
            f"Сегодня:\n{'\n'.join(holidays)}"
        )
        return True

    def help(self) -> str | None:
        return (
            "/holidays - узнать какие сегодня праздники"
        )

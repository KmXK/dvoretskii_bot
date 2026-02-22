import asyncio
import json
import logging
import re
import shlex
from os import environ
from urllib.parse import quote

from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.limiter import Duration, check_limit


logger = logging.getLogger(__name__)


@CommandHandler(
    "link",
    arguments_template=r"((?P<url>\S+)( (?P<short>\S+))?)?",
    arguments_mapping={
        "url": lambda x: x or "",
        "short": lambda x: x or "",
    },
)
class LinkHandler(Handler):
    async def chat(self, context: ChatBotContext, url: str, short: str):
        check_limit("link_per_user", 2, 20 * Duration.SECOND, name=str(context.message.from_user.id))

        if not url:
            reply = context.message.reply_to_message
            if reply and reply.text:
                match = re.search(r'(https?://\S+|\S+\.\S+/\S*|\S+\.[a-z]{2,})', reply.text)
                if match:
                    url = match.group(0)
            if not url:
                await context.message.reply_text("Укажи ссылку или ответь на сообщение со ссылкой")
                return True

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        template = environ.get("SHORTENER_CURL_TEMPLATE")
        if not template:
            await context.message.reply_text("Сервис сокращения ссылок не настроен")
            return True

        cmd = template.replace("{url}", quote(url, safe="")).replace("{short}", quote(short, safe=""))

        try:
            args = shlex.split(cmd)
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"Error: {stderr.decode().strip()}")
                await context.message.reply_text("Ошибка сокращения ссылки")
                return True

            logger.info(f"Result: {json.loads(stdout.decode().strip())}")
            await context.message.reply_text(json.loads(stdout.decode().strip())["result"])
        except Exception as e:
            logger.exception(e)
            await context.message.reply_text("Ошибка сокращения ссылки")

        return True

    def help(self) -> str | None:
        return "/link [<url>] [<short>] - создать короткую ссылку (или реплай на сообщение со ссылкой)"

    def prompt(self) -> str | None:
        return (
            "▶ /link — создание коротких ссылок\n"
            "  Синтаксис: /link <url> [<короткое_имя>]\n"
            "  Примеры:\n"
            "  - «сократи ссылку https://example.com» → /link https://example.com\n"
            "  - «сократи https://example.com как ex» → /link https://example.com ex"
        )
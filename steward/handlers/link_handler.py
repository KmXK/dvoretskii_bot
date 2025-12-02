import asyncio
import json
import shlex
from os import environ
from urllib.parse import quote

from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler, required
from steward.handlers.handler import Handler


@CommandHandler(
    "link",
    arguments_template=r"(?P<url>\S+)( (?P<short>\S+))?",
    arguments_mapping={
        "url": required(str),
        "short": lambda x: x or "",
    },
)
class LinkHandler(Handler):
    async def chat(self, context: ChatBotContext, url: str, short: str):
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
                await context.message.reply_text(f"Ошибка: {stderr.decode().strip()}")
                return True

            await context.message.reply_text(json.loads(stdout.decode().strip())["result"])
        except Exception as e:
            await context.message.reply_text(f"Ошибка: {e}")

        return True

    def help(self) -> str | None:
        return "/link <url> [<short>] - создать короткую ссылку"

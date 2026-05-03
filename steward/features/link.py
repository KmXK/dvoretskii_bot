import asyncio
import json
import logging
import re
import shlex
from os import environ
from urllib.parse import quote

from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


_URL_RE = re.compile(r"(https?://\S+|\S+\.\S+/\S*|\S+\.[a-z]{2,})")


class LinkFeature(Feature):
    command = "link"
    description = "Создать короткую ссылку"
    help_examples = [
        "«сократи ссылку https://example.com» → /link https://example.com",
        "«сократи https://example.com как ex» → /link https://example.com ex",
    ]

    @subcommand("", description="Сократить URL из реплая")
    async def from_reply(self, ctx: FeatureContext):
        url = self._extract_from_reply(ctx)
        if not url:
            await ctx.reply("Укажи ссылку или ответь на сообщение со ссылкой")
            return
        await self._shorten(ctx, url, "")

    @subcommand("<url:str>", description="Сократить URL")
    async def shorten_one(self, ctx: FeatureContext, url: str):
        await self._shorten(ctx, url, "")

    @subcommand("<url:str> <short:str>", description="Сократить с алиасом")
    async def shorten_alias(self, ctx: FeatureContext, url: str, short: str):
        await self._shorten(ctx, url, short)

    def _extract_from_reply(self, ctx: FeatureContext) -> str:
        if ctx.message is None:
            return ""
        reply = ctx.message.reply_to_message
        if reply and reply.text:
            m = _URL_RE.search(reply.text)
            if m:
                return m.group(0)
        return ""

    async def _shorten(self, ctx: FeatureContext, url: str, short: str):
        check_limit("link_per_user", 2, 20 * Duration.SECOND, name=str(ctx.user_id))
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        template = environ.get("SHORTENER_CURL_TEMPLATE")
        if not template:
            await ctx.reply("Сервис сокращения ссылок не настроен")
            return
        cmd = template.replace("{url}", quote(url, safe="")).replace(
            "{short}", quote(short, safe="")
        )
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
                await ctx.reply("Ошибка сокращения ссылки")
                return
            result = json.loads(stdout.decode().strip())["result"]
            await ctx.reply(result)
        except Exception as e:
            logger.exception(e)
            await ctx.reply("Ошибка сокращения ссылки")

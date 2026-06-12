import asyncio
import json
import logging
import shlex
from os import environ
from urllib.parse import quote

logger = logging.getLogger(__name__)


class ShortenerNotConfigured(RuntimeError):
    pass


async def shorten_url(url: str, short: str = "") -> str:
    """Сокращает ссылку через внешний сервис (SHORTENER_CURL_TEMPLATE)."""
    template = environ.get("SHORTENER_CURL_TEMPLATE")
    if not template:
        raise ShortenerNotConfigured("SHORTENER_CURL_TEMPLATE is not set")
    cmd = template.replace("{url}", quote(url, safe="")).replace(
        "{short}", quote(short, safe="")
    )
    args = shlex.split(cmd)
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"shortener failed: {stderr.decode().strip()}")
    return json.loads(stdout.decode().strip())["result"]

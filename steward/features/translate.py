import logging
import re
from os import environ

from aiohttp import ClientSession

from steward.framework import Feature, FeatureContext, on_message, subcommand
from steward.helpers.command_validation import (
    ValidationArgumentsError,
    validate_arguments,
)
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


_LANG_REGEX = r"((?P<from_lang>[a-zA-Z]+)/)?(?P<to_lang>[a-zA-Z]+)"
_COMMAND_RE = re.compile(_LANG_REGEX + r"( (?P<text>.+))?")
_BRACKET_RE = re.compile(r"\[" + _LANG_REGEX + r"\]( (?P<text>.+))?")


class TranslateFeature(Feature):
    command = "translate"
    description = "Перевод текста"
    help_examples = [
        "«переведи на английский привет мир» → /translate en привет мир",
        "«переведи с немецкого на русский Guten Tag» → /translate de/ru Guten Tag",
        "«переведи на японский доброе утро» → /translate ja доброе утро",
    ]

    @subcommand(_COMMAND_RE, description="Перевести текст")
    async def translate_cmd(self, ctx: FeatureContext, **kw):
        await self._dispatch(ctx, kw)

    @on_message
    async def bracket_form(self, ctx: FeatureContext) -> bool:
        if ctx.message is None or not ctx.message.text:
            return False
        parsed = validate_arguments(ctx.message.text, _BRACKET_RE)
        if not parsed:
            return False
        await self._dispatch(ctx, parsed)
        return True

    async def _dispatch(self, ctx: FeatureContext, parsed: dict):
        if not parsed.get("text"):
            reply = ctx.message.reply_to_message if ctx.message else None
            if reply is None or reply.text is None:
                raise ValidationArgumentsError()
            parsed["text"] = reply.text

        from_lang = (parsed.get("from_lang") or "").lower() or None
        lang = parsed["to_lang"].lower()
        text = parsed["text"]

        check_limit(self, 20, Duration.MINUTE, name=str(ctx.user_id))

        async with ClientSession() as session:
            async with session.post(
                "https://translate.api.cloud.yandex.net/translate/v2/translate",
                json={
                    "texts": [text],
                    "targetLanguageCode": lang,
                    "sourceLanguageCode": from_lang,
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Api-Key {environ.get('TRANSLATE_KEY_SECRET')}",
                },
            ) as response:
                data = await response.json()
                if (
                    "message" in data
                    and "unsupported target_language_code" in data["message"]
                ):
                    await ctx.reply(f"Язык {lang} не поддерживается для перевода")
                    return
                translated = data["translations"][0]["text"]
                await ctx.reply(translated)

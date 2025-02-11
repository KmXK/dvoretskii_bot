import logging
import re
from os import environ

from aiohttp import ClientSession

from steward.handlers.handler import Handler, validate_command_msg
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


# xx or xx/xx ("xx/" part is optional)
# means from_lang/to_lang
LANG_REGEX = r"((?P<from_lang>[a-zA-Z]+)/)?(?P<to_lang>[a-zA-Z]+)"


class TranslateHandler(Handler):
    async def chat(self, update, context):
        assert update.message and update.message.text
        if validate_command_msg(update, ["translate"]):
            # TODO: получать сразу параметры команды из validate_command_msg или ещё одного вызова
            # чтобы не иметь эту логику в хендлерах
            match = re.match(
                r"^" + LANG_REGEX + r" (?P<text>.+)$",
                " ".join(update.message.text.split(" ")[1:]),
            )

            if not match:
                await update.message.reply_text(
                    "Использование: /translate [<from_code_language>/]<to_code_language> <text>"
                )
                return True

        # TODO: сделать подмену сообщений в правилах и поменять на /translate
        else:
            match = re.match(
                r"^\[" + LANG_REGEX + r"\] (?P<text>.+)$",
                update.message.text,
            )
            if not match:
                return False

        from_lang: str | None = match.group("from_lang")
        lang: str = match.group("to_lang")
        text: str = match.group("text")

        check_limit(self, 20, Duration.MINUTE, name=str(update.message.from_user.id))

        async with ClientSession() as session:
            async with session.post(
                "https://translate.api.cloud.yandex.net/translate/v2/translate",
                json={
                    "texts": [text],
                    "targetLanguageCode": lang,
                    "sourceLanguageCode": from_lang if from_lang else None,
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Api-Key {environ.get('TRANSLATE_KEY_SECRET')}",
                },
            ) as response:
                json = await response.json()

                logger.info(f"got response {json}")

                if (
                    "message" in json
                    and "unsupported target_language_code" in json["message"]
                ):
                    await update.message.reply_text(
                        f"Язык {lang} не поддерживается для перевода"
                    )
                    return True

                text = json["translations"][0]["text"]
                await update.message.reply_text(text)

        return True

    def help(self) -> str | None:
        return "/translate [<from_code_language>/]<to_code_language> <text> - перевод текста"

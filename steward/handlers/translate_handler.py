import logging
import re
from os import environ

from aiohttp import ClientSession

from steward.handlers.handler import Handler, validate_command_msg
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


class TranslateHandler(Handler):
    async def chat(self, update, context):
        assert update.message and update.message.text
        if validate_command_msg(update, ["translate"]):
            parts = update.message.text.split(" ")

            if len(parts) < 3:
                await update.message.reply_text(
                    "Использование: /translate <lang_code> <text>"
                )
                return True

            lang = parts[1]

            if len(lang) != 2:
                await update.message.reply_text(
                    "Код языка должен состоять из двух букв"
                )
                return True

            text = " ".join(parts[2:])
        # TODO: сделать подмену сообщений в правилах и поменять на /translate
        elif re.match(r"^\[[a-zA-Z]{2}\]", update.message.text) is not None:
            lang = update.message.text[1:3]
            text = update.message.text[4:]
        else:
            return False

        check_limit(self, 10, Duration.MINUTE)

        async with ClientSession() as session:
            async with session.post(
                "https://translate.api.cloud.yandex.net/translate/v2/translate",
                json={"texts": [text], "targetLanguageCode": lang},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Api-Key {environ.get('TRANSLATE_KEY_SECRET')}",
                },
            ) as response:
                json = await response.json()

                logger.info(f"got response {json}")

                if "unsupported target_language_code" in json["message"]:
                    await update.message.reply_text(
                        f"Язык {lang} не поддерживается для перевода"
                    )
                    return True

                text = json["translations"][0]["text"]
                await update.message.reply_text(text)

        return True

    def help(self) -> str | None:
        return "/translate <lang_code> <text> - перевод текста"

import logging
from os import environ

from aiohttp import ClientSession

from steward.handlers.handler import CommandHandler, Handler


@CommandHandler("translate")
class TranslateHandler(Handler):
    async def chat(self, update, context):
        assert update.message and update.message.text

        parts = update.message.text.split(" ")

        if len(parts) < 3:
            await update.message.reply_text(
                "Использование: /translate <lang_code> <text>"
            )
            return True

        lang = parts[1]

        if len(lang) != 2:
            await update.message.reply_text("Код языка должен состоять из двух букв")
            return True

        text = " ".join(parts[2:])

        logging.info(environ.get("TRANSLATE_KEY_SECRET"))

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
                text = json["translations"][0]["text"]
                await update.message.reply_text(text)

    def help(self) -> str | None:
        return "/translate <lang_code> <text> - перевод текста"

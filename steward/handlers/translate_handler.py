import logging
from os import environ

from aiohttp import ClientSession

from steward.handlers.handler import Handler
from steward.helpers.command_validation import (
    ValidationArgumentsError,
    validate_arguments,
    validate_command_msg,
)
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


# xx or xx/xx ("xx/" part is optional)
# means from_lang/to_lang
LANG_REGEX = r"((?P<from_lang>[a-zA-Z]+)/)?(?P<to_lang>[a-zA-Z]+)"


class TranslateHandler(Handler):
    async def chat(self, context):
        if validation_result := validate_command_msg(
            context.update,
            "translate",
            LANG_REGEX + r"( (?P<text>.+))?",
        ):
            if not validation_result:
                raise ValidationArgumentsError()

            assert validation_result.args

            if validation_result.args.get("text") is None:
                if (
                    context.message.reply_to_message is None
                    or context.message.reply_to_message.text is None
                ):
                    raise ValidationArgumentsError()

                validation_result.args["text"] = context.message.reply_to_message.text

            parsed_args = validation_result.args

        # TODO: сделать подмену сообщений в правилах и поменять на /translate
        else:
            assert context.message.text
            parsed_args = validate_arguments(
                context.message.text,
                r"\[" + LANG_REGEX + r"\]( (?P<text>.+))?",
            )

            if not parsed_args:
                return False

            if parsed_args.get("text") is None:
                if (
                    context.message.reply_to_message is None
                    or context.message.reply_to_message.text is None
                ):
                    raise ValidationArgumentsError()

                parsed_args["text"] = context.message.reply_to_message.text

        from_lang = parsed_args.get("from_lang")
        if from_lang is not None:
            from_lang = from_lang.lower()
        lang: str = parsed_args["to_lang"].lower()
        text: str = parsed_args["text"]

        check_limit(self, 20, Duration.MINUTE, name=str(context.message.from_user.id))

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
                    await context.message.reply_text(
                        f"Язык {lang} не поддерживается для перевода"
                    )
                    return True

                text = json["translations"][0]["text"]
                await context.message.reply_text(text)

        return True

    def help(self) -> str | None:
        return "/translate [<from_code_language>/]<to_code_language> <text> - перевод текста"

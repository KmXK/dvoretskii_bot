from os import environ

from aiohttp import ClientSession

from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler


@CommandHandler("pasha", only_admin=True)
class PashaHandler(Handler):
    async def chat(self, context):
        async with ClientSession() as session:
            async with session.post(
                "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                json={
                    "modelUri": f"{environ.get('AI_MODEL_URI')}",
                    "messages": [
                        {
                            "role": "user",
                            "text": context.message.text,
                        },
                    ],
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Api-Key {environ.get('AI_KEY_SECRET')}",
                },
            ) as response:
                json = await response.json()
                await context.message.reply_text(
                    json["result"]["alternatives"][0]["message"]["text"]
                )

    def help(self):
        return "/pasha - поговорить с ии пашей"

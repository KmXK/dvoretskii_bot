import logging
from os import environ

from aiohttp import ClientSession
from openai import OpenAI

logger = logging.getLogger(__name__)


class AIModels:
    YANDEXGPT_PASHA = "YANDEXGPT_PASHA"
    YANDEXGPT_5_PRO = "YANDEXGPT_5_PRO"
    LLAMA_70B = "LLAMA_70B"


with open("jailbreak.txt", "r", encoding="utf-8") as f:
    JAILBREAK_PROMPT = f.read()
with open("pasha.txt", "r", encoding="utf-8") as f:
    PASHA_PROMPT = f.read()


async def make_ai_query(model, text, system_prompt=None):
    text = system_prompt + ". " + text if system_prompt else text

    async with ClientSession() as session:
        async with session.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            json={
                "modelUri": f"{environ.get('AI_MODEL_' + model)}",
                "messages": [
                    {
                        "role": "user",
                        "text": text,
                    },
                ],
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Api-Key {environ.get('AI_KEY_SECRET')}",
            },
        ) as response:
            json = await response.json()

            logger.info(json)

            return json["result"]["alternatives"][0]["message"]["text"]


deepseek_client = None


def make_deepseek_query(text, system_prompt=""):
    global deepseek_client
    if not deepseek_client:
        deepseek_client = OpenAI(
            api_key=environ.get("DEEPSEEK_KEY"), base_url="https://api.deepseek.com"
        )

    response = deepseek_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        stream=False,
    )
    assert isinstance(response.choices[0].message.content, str)
    return response.choices[0].message.content

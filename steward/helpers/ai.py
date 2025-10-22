import logging
from os import environ

from aiohttp import ClientSession
from openai import OpenAI

from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


class AIModels:
    YANDEXGPT_PASHA = "YANDEXGPT_PASHA"
    YANDEXGPT_5_PRO = "YANDEXGPT_5_PRO"
    LLAMA_70B = "LLAMA_70B"


with open("jailbreak.txt", "r", encoding="utf-8") as f:
    JAILBREAK_PROMPT = f.read()
with open("pasha.txt", "r", encoding="utf-8") as f:
    PASHA_PROMPT = f.read()


async def make_ai_query_ext(
    user_id,
    model,
    messages: list[tuple[str, str]],
    system_prompt=None,
):
    check_limit("ai_total", 20, Duration.MINUTE, name="total")
    check_limit("ai_per_user", 7, 20 * Duration.SECOND, name=user_id)

    async with ClientSession() as session:
        async with session.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            json={
                "modelUri": f"{environ.get('AI_MODEL_' + model)}",
                "messages": [
                    {
                        "role": "system",
                        "text": system_prompt,
                    },
                    *[{"role": role, "text": text} for role, text in messages],
                ],
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Api-Key {environ.get('AI_KEY_SECRET')}",
            },
        ) as response:
            json = await response.json()
            try:
                return json["result"]["alternatives"][0]["message"]["text"]
            except Exception as e:
                logger.error(f"AI request failed: {json}")
                raise e


async def make_ai_query(user_id, model, text, system_prompt=None):
    return await make_ai_query_ext(user_id, model, [("user", text)], system_prompt)


deepseek_client = None


def make_deepseek_query(user_id, text, system_prompt=""):
    global deepseek_client
    if not deepseek_client:
        deepseek_client = OpenAI(
            api_key=environ.get("DEEPSEEK_KEY"), base_url="https://api.deepseek.com"
        )

    check_limit("deepseek_total", 20, Duration.MINUTE)
    check_limit("deepseek_per_user", 7, 20 * Duration.SECOND, name=user_id)

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

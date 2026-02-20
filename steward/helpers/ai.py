import asyncio
import logging
from os import environ

import httpx
from aiohttp import ClientSession
from openai import OpenAI

from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


class YandexModelTypes:
    YANDEXGPT_PASHA = "YANDEXGPT_PASHA"
    YANDEXGPT_5_PRO = "YANDEXGPT_5_PRO"
    LLAMA_70B = "LLAMA_70B"


class OpenRouterModel:
    GROK_4_FAST = "x-ai/grok-4-fast"
    AUTO = "openrouter/auto"


def get_prompt(prompt_name: str):
    with open(f"prompts/{prompt_name}.txt", "r", encoding="utf-8") as f:
        return f.read()

JAILBREAK_PROMPT = get_prompt("jailbreak")
PASHA_PROMPT = get_prompt("pasha")
TAROT_PROMPT = get_prompt("tarot")
GROK_SHORT_AGGRESSIVE = get_prompt("grok_short_aggressive")
CONCISE = get_prompt("concise")
BILL_OCR_PROMPT = get_prompt("bill_ocr")


async def make_yandex_ai_query(
    user_id,
    messages: list[tuple[str, str]],
    system_prompt=None,
    model: YandexModelTypes = YandexModelTypes.YANDEXGPT_5_PRO,
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


openrouter_client = None


async def make_openrouter_query(user_id, model, messages: list[tuple[str, str]], system_prompt=""):
    global openrouter_client
    if not openrouter_client:
        proxy = environ.get("DOWNLOAD_PROXY")
        openrouter_client = OpenAI(
            api_key=environ.get("OPENROUTER_KEY"),
            base_url="https://openrouter.ai/api/v1",
            timeout=httpx.Timeout(120.0, connect=30.0),
            http_client=httpx.Client(proxy=proxy) if proxy else None,
        )

    check_limit("openrouter_total", 20, Duration.MINUTE)
    check_limit("openrouter_per_user", 7, 20 * Duration.SECOND, name=user_id)

    def _call():
        return openrouter_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                *[{"role": role, "content": content} for role, content in messages],
            ],
            stream=False,
        )

    response = await asyncio.to_thread(_call)
    assert isinstance(response.choices[0].message.content, str)
    return response.choices[0].message.content

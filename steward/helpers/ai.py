import asyncio
import logging
import threading
from os import environ
from typing import AsyncIterator

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


_YANDEX_COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


def _yandex_payload(
    messages: list[tuple[str, str]],
    system_prompt: str | None,
    model: str,
    stream: bool,
) -> dict:
    return {
        "modelUri": f"{environ.get('AI_MODEL_' + model)}",
        "completionOptions": {"stream": stream},
        "messages": [
            {"role": "system", "text": system_prompt or ""},
            *[{"role": role, "text": text} for role, text in messages],
        ],
    }


def _yandex_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {environ.get('AI_KEY_SECRET')}",
    }


def _check_yandex_limits(user_id) -> None:
    check_limit("ai_total", 20, Duration.MINUTE, name="total")
    check_limit("ai_per_user", 7, 20 * Duration.SECOND, name=user_id)


async def make_yandex_ai_query(
    user_id,
    messages: list[tuple[str, str]],
    system_prompt=None,
    model: YandexModelTypes = YandexModelTypes.YANDEXGPT_5_PRO,
):
    _check_yandex_limits(user_id)

    async with ClientSession() as session:
        async with session.post(
            _YANDEX_COMPLETION_URL,
            json=_yandex_payload(messages, system_prompt, model, stream=False),
            headers=_yandex_headers(),
        ) as response:
            data = await response.json()
            try:
                return data["result"]["alternatives"][0]["message"]["text"]
            except Exception as e:
                logger.error(f"AI request failed: {data}")
                raise e


async def make_yandex_ai_stream(
    user_id,
    messages: list[tuple[str, str]],
    system_prompt=None,
    model: YandexModelTypes = YandexModelTypes.YANDEXGPT_5_PRO,
) -> AsyncIterator[str]:
    """Async generator yielding Yandex GPT deltas.

    Yandex streams JSON-Lines where each line contains the *accumulated* text
    for the current alternative, so we track the previous value and yield only
    the difference.
    """
    import json as _json

    _check_yandex_limits(user_id)

    async def _iter():
        prev_text = ""
        async with ClientSession() as session:
            async with session.post(
                _YANDEX_COMPLETION_URL,
                json=_yandex_payload(messages, system_prompt, model, stream=True),
                headers=_yandex_headers(),
            ) as response:
                async for raw in response.content:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    try:
                        data = _json.loads(line)
                    except _json.JSONDecodeError:
                        logger.debug("yandex stream: non-json line: %s", line[:200])
                        continue
                    try:
                        current = data["result"]["alternatives"][0]["message"]["text"]
                    except (KeyError, IndexError, TypeError):
                        err = data.get("error") if isinstance(data, dict) else None
                        if err:
                            raise RuntimeError(f"yandex stream error: {err}")
                        continue
                    if not isinstance(current, str):
                        continue
                    if current.startswith(prev_text):
                        delta = current[len(prev_text):]
                    else:
                        delta = current  # fallback: full-replace
                    prev_text = current
                    if delta:
                        yield delta

    return _iter()


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


def _ensure_openrouter_client():
    global openrouter_client
    if not openrouter_client:
        proxy = environ.get("DOWNLOAD_PROXY")
        openrouter_client = OpenAI(
            api_key=environ.get("OPENROUTER_KEY"),
            base_url="https://openrouter.ai/api/v1",
            timeout=httpx.Timeout(120.0, connect=30.0),
            http_client=httpx.Client(proxy=proxy) if proxy else None,
        )
    return openrouter_client


def _openrouter_payload(model, messages: list[tuple[str, str]], system_prompt: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *[{"role": role, "content": content} for role, content in messages],
        ],
    }


def _check_openrouter_limits(user_id) -> None:
    check_limit("openrouter_total", 20, Duration.MINUTE)
    check_limit("openrouter_per_user", 7, 20 * Duration.SECOND, name=user_id)


async def make_openrouter_query(user_id, model, messages: list[tuple[str, str]], system_prompt=""):
    client = _ensure_openrouter_client()
    _check_openrouter_limits(user_id)
    payload = _openrouter_payload(model, messages, system_prompt)

    def _call():
        return client.chat.completions.create(**payload, stream=False)

    response = await asyncio.to_thread(_call)
    assert isinstance(response.choices[0].message.content, str)
    return response.choices[0].message.content


async def make_openrouter_stream(
    user_id,
    model,
    messages: list[tuple[str, str]],
    system_prompt: str = "",
) -> AsyncIterator[str]:
    """Async generator yielding content deltas from OpenRouter (stream=True).

    The underlying OpenAI SDK is sync, so we pump chunks from a worker thread
    into an asyncio.Queue. Rate limits are applied once up front, same as the
    non-streaming call.
    """
    client = _ensure_openrouter_client()
    _check_openrouter_limits(user_id)
    payload = _openrouter_payload(model, messages, system_prompt)

    loop = asyncio.get_running_loop()
    q: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()

    def _pump():
        try:
            stream = client.chat.completions.create(**payload, stream=True)
            for event in stream:
                try:
                    delta = event.choices[0].delta.content
                except (IndexError, AttributeError):
                    delta = None
                if delta:
                    asyncio.run_coroutine_threadsafe(q.put(("chunk", delta)), loop)
            asyncio.run_coroutine_threadsafe(q.put(("done", None)), loop)
        except Exception as e:
            logger.exception("openrouter stream failed: %s", e)
            asyncio.run_coroutine_threadsafe(q.put(("error", str(e))), loop)

    threading.Thread(target=_pump, daemon=True).start()

    async def _iter():
        while True:
            kind, payload = await q.get()
            if kind == "chunk":
                assert payload is not None
                yield payload
            elif kind == "done":
                return
            else:  # error
                raise RuntimeError(f"openrouter stream: {payload}")

    return _iter()

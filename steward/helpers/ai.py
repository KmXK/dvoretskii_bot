import asyncio
import logging
import re
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
    GROK_3_BETA = "x-ai/grok-3-beta"
    GEMINI_25_FLASH = "google/gemini-2.5-flash"
    AUTO = "openrouter/auto"
    # Small/fast model for low-latency side tasks (placeholders, classifications).
    FAST = "google/gemini-2.5-flash"


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
_YANDEX_OPENAI_URL = "https://llm.api.cloud.yandex.net/v1/chat/completions"


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
    model: str = YandexModelTypes.YANDEXGPT_5_PRO,
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


def _yandex_vlm_model_uri() -> str | None:
    return environ.get("AI_MODEL_VLM")


async def make_yandex_vlm_describe(
    user_id,
    prompt: str,
    images_b64: list[str],
    max_tokens: int = 200,
) -> str:
    """Single-turn VLM call via Yandex OpenAI-compatible endpoint.

    Accepts several base64 JPEG images in one request — cheaper than N single-image calls.
    """
    _check_yandex_limits(user_id)
    model = _yandex_vlm_model_uri()
    if not model:
        raise RuntimeError("Yandex VLM not configured: set AI_MODEL_VLM in .env")

    content: list[dict] = [{"type": "text", "text": prompt}]
    for b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(_YANDEX_OPENAI_URL, json=payload, headers=_yandex_headers())
        if r.status_code >= 400:
            body = r.text[:1000]
            logger.error(
                "VLM HTTP %s for model=%s images=%d max_tokens=%d body=%s",
                r.status_code, model, len(images_b64), max_tokens, body,
            )
            r.raise_for_status()
        data = r.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        logger.error("VLM response malformed: %s", data)
        raise e
    if not isinstance(text, str):
        raise RuntimeError(f"VLM response content is not a string: {type(text).__name__}")
    return text.strip()


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


def _openrouter_payload(
    model,
    messages: list[tuple[str, str]],
    system_prompt: str,
    max_tokens: int | None = None,
) -> dict:
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *[{"role": role, "content": content} for role, content in messages],
        ],
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return payload


def _check_openrouter_limits(user_id) -> None:
    check_limit("openrouter_total", 20, Duration.MINUTE)
    check_limit("openrouter_per_user", 7, 20 * Duration.SECOND, name=user_id)


async def make_openrouter_query(
    user_id,
    model,
    messages: list[tuple[str, str]],
    system_prompt: str = "",
    max_tokens: int | None = None,
    timeout_seconds: float | None = None,
):
    client = _ensure_openrouter_client()
    _check_openrouter_limits(user_id)
    payload = _openrouter_payload(model, messages, system_prompt, max_tokens)

    def _call():
        return client.chat.completions.create(**payload, stream=False)

    if timeout_seconds is not None:
        response = await asyncio.wait_for(
            asyncio.to_thread(_call), timeout=timeout_seconds
        )
    else:
        response = await asyncio.to_thread(_call)
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content:
        raise ValueError(
            f"Model returned empty response (finish_reason={response.choices[0].finish_reason})"
        )
    return content


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


_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class Model:
    SMART = "smart"
    FAST = "fast"


_MODEL_MAP: dict[str, dict[str, str]] = {
    Model.SMART: {
        "nvidia": environ.get("NVIDIA_SMART_MODEL") or "google/gemma-3-27b-it",
        "openrouter": OpenRouterModel.GROK_4_FAST,
        "yandex": YandexModelTypes.YANDEXGPT_5_PRO,
    },
    Model.FAST: {
        "nvidia": environ.get("NVIDIA_FAST_MODEL") or "google/gemma-3-12b-it",
        "openrouter": OpenRouterModel.FAST,
        "yandex": YandexModelTypes.YANDEXGPT_5_PRO,
    },
}

_NVIDIA_OCR_MODEL = environ.get("NVIDIA_OCR_MODEL") or "meta/llama-3.2-90b-vision-instruct"


def resolve_model(model: str, provider: str) -> str:
    entry = _MODEL_MAP.get(model)
    return entry[provider] if entry else model


nvidia_client = None


def _ensure_nvidia_client():
    global nvidia_client
    if not nvidia_client:
        api_key = environ.get("NVIDIA_API_KEY")
        if not api_key:
            raise RuntimeError("NVIDIA_API_KEY is not set")
        nvidia_client = OpenAI(
            api_key=api_key,
            base_url=_NVIDIA_BASE_URL,
            timeout=httpx.Timeout(120.0, connect=30.0),
            http_client=httpx.Client(trust_env=False),
        )
    return nvidia_client


def nvidia_is_configured() -> bool:
    return bool(environ.get("NVIDIA_API_KEY"))


def _check_nvidia_limits(user_id) -> None:
    check_limit("nvidia_total", 30, Duration.MINUTE)
    check_limit("nvidia_per_user", 10, 20 * Duration.SECOND, name=user_id)


def _clean_nvidia_text(text: str) -> str:
    return _THINK_TAG_RE.sub("", text).strip()


async def make_nvidia_query(
    user_id,
    model: str,
    messages: list[tuple[str, str]],
    system_prompt: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> str:
    client = _ensure_nvidia_client()
    _check_nvidia_limits(user_id)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *[{"role": role, "content": content} for role, content in messages],
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    response = await asyncio.to_thread(
        lambda: client.chat.completions.create(**payload, stream=False)
    )
    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise RuntimeError(f"NVIDIA response is not a string: {type(content).__name__}")
    return _clean_nvidia_text(content)


async def make_chat_query(
    user_id,
    model: str,
    messages: list[tuple[str, str]],
    system_prompt: str = "",
) -> str:
    if nvidia_is_configured():
        try:
            return await make_nvidia_query(
                user_id, resolve_model(model, "nvidia"), messages, system_prompt
            )
        except Exception as e:
            logger.warning("chat_query: NVIDIA failed, falling back to Yandex: %s", e)
    return await make_yandex_ai_query(
        user_id, messages, system_prompt, resolve_model(model, "yandex")
    )


async def make_nvidia_stream(
    user_id,
    model: str,
    messages: list[tuple[str, str]],
    system_prompt: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> AsyncIterator[str]:
    client = _ensure_nvidia_client()
    _check_nvidia_limits(user_id)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *[{"role": role, "content": content} for role, content in messages],
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    loop = asyncio.get_running_loop()
    q: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
    in_think = [False]

    def _pump():
        try:
            stream = client.chat.completions.create(**payload, stream=True)
            for event in stream:
                try:
                    delta = event.choices[0].delta.content
                except (IndexError, AttributeError):
                    delta = None
                if not delta:
                    continue
                if in_think[0]:
                    end = delta.find("</think>")
                    if end < 0:
                        continue
                    delta = delta[end + len("</think>"):]
                    in_think[0] = False
                    if not delta:
                        continue
                start = delta.find("<think>")
                if start >= 0:
                    before = delta[:start]
                    rest = delta[start + len("<think>"):]
                    end = rest.find("</think>")
                    if end >= 0:
                        delta = before + rest[end + len("</think>"):]
                    else:
                        in_think[0] = True
                        delta = before
                    if not delta:
                        continue
                asyncio.run_coroutine_threadsafe(q.put(("chunk", delta)), loop)
            asyncio.run_coroutine_threadsafe(q.put(("done", None)), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(q.put(("error", str(e))), loop)

    threading.Thread(target=_pump, daemon=True).start()

    async def _iter():
        while True:
            kind, data = await q.get()
            if kind == "chunk":
                assert data is not None
                yield data
            elif kind == "done":
                return
            else:
                raise RuntimeError(f"nvidia stream: {data}")

    return _iter()


async def make_text_query(
    user_id,
    model: str,
    messages: list[tuple[str, str]],
    system_prompt: str = "",
) -> str:
    if nvidia_is_configured():
        try:
            return await make_nvidia_query(
                user_id, resolve_model(model, "nvidia"), messages, system_prompt
            )
        except Exception as e:
            logger.warning("text_query: NVIDIA failed, falling back to OpenRouter: %s", e)
    return await make_openrouter_query(
        user_id, resolve_model(model, "openrouter"), messages, system_prompt
    )


async def make_text_stream(
    user_id,
    model: str,
    messages: list[tuple[str, str]],
    system_prompt: str = "",
) -> AsyncIterator[str]:
    or_model = resolve_model(model, "openrouter")
    if nvidia_is_configured():
        try:
            nv = await make_nvidia_stream(
                user_id, resolve_model(model, "nvidia"), messages, system_prompt
            )

            async def _gen():
                got = False
                try:
                    async for chunk in nv:
                        got = True
                        yield chunk
                except Exception as e:
                    if got:
                        logger.warning("NVIDIA stream interrupted: %s", e)
                        return
                    logger.warning("NVIDIA stream failed, falling back to OpenRouter: %s", e)
                    fb = await make_openrouter_stream(user_id, or_model, messages, system_prompt)
                    async for chunk in fb:
                        yield chunk
                    return
                if not got:
                    logger.warning("NVIDIA stream empty, falling back to OpenRouter")
                    fb = await make_openrouter_stream(user_id, or_model, messages, system_prompt)
                    async for chunk in fb:
                        yield chunk

            return _gen()
        except Exception as e:
            logger.warning("text_stream: NVIDIA init failed: %s", e)
    return await make_openrouter_stream(user_id, or_model, messages, system_prompt)


async def make_nvidia_vlm_describe(
    user_id,
    prompt: str,
    images_b64: list[str],
    max_tokens: int = 1024,
    model: str | None = None,
) -> str:
    client = _ensure_nvidia_client()
    _check_nvidia_limits(user_id)
    content: list[dict] = [{"type": "text", "text": prompt}]
    for b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
    payload = {
        "model": model or _NVIDIA_OCR_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    response = await asyncio.to_thread(
        lambda: client.chat.completions.create(**payload, stream=False)
    )
    out = response.choices[0].message.content
    if not isinstance(out, str):
        raise RuntimeError(f"NVIDIA VLM response is not a string: {type(out).__name__}")
    return _clean_nvidia_text(out)

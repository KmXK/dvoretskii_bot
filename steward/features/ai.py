import logging
import random
import traceback

from steward.framework import Feature, FeatureContext, on_init, subcommand
from steward.helpers.ai import (
    GROK_SHORT_AGGRESSIVE,
    Model,
    OpenRouterModel,
    make_openrouter_query,
    make_openrouter_stream,
    make_text_query,
    make_text_stream,
)
from steward.helpers.ai_context import (
    execute_ai_request_streaming,
    register_ai_handler,
)
from steward.helpers.thinking import ensure_cached as ensure_thinking_phrases, try_contextual_placeholder

logger = logging.getLogger(__name__)


_REPO_HOLDER = {"repo": None}


_ONLINE_PHRASES = (
    "Лезу в инет",
    "Пошёл гуглить",
    "Открываю Хром",
    "Ищу свежие пруфы",
    "Зову тётю Гугл",
    "Шарюсь по новостям",
    "Сверяюсь с реальностью",
    "Достаю из ВВВ",
)


def _build_users_descriptions_block() -> str:
    repo = _REPO_HOLDER["repo"]
    if repo is None:
        return "- Пока нет описаний."
    descriptions = []
    for user in repo.db.users:
        if not user.stand_name or not user.stand_description:
            continue
        descriptions.append(f"- {user.stand_name.strip()}: {user.stand_description.strip()}")
    if not descriptions:
        return "- Пока нет описаний."
    return "\n".join(descriptions)


def _build_system_prompt() -> str:
    users = _build_users_descriptions_block()
    return GROK_SHORT_AGGRESSIVE.replace("{{USERS_DESCRIPTIONS}}", users)


_ONLINE_STYLE_SUFFIX = """\
Когда ссылаешься на источник из веб-поиска — оборачивай в Markdown-ссылку САМУ фразу из текста, к которой относится источник: [часть фразы](url). НЕ используй сноски, цифры в скобках, [[1]], [1], (1) и не приклеивай ссылки в конце предложения отдельно. Ссылка должна быть органичной частью предложения, без отдельных пометок «источник» или подобного. Если на одну фразу несколько источников — выбери самый релевантный, остальные не показывай."""


def _build_online_system_prompt() -> str:
    return _build_system_prompt() + "\n\n" + _ONLINE_STYLE_SUFFIX


_ROUTER_PROMPT = """Решаешь, нужен ли веб-поиск чтобы ответить на запрос.

Запрос: {query}

Нужен веб (YES):
- свежие новости, события, происшествия
- актуальные цены, курсы, котировки, расписания, погода
- проверка фактов, которые могут устаревать
- слова "сегодня", "сейчас", "недавно", "последний", "новый"
- что-то про конкретных людей/компании в настоящем времени (что делают, где, что нового)

НЕ нужен веб (NO):
- общие знания, история, факты из учебников
- объяснения, определения
- математика, код, логика
- юмор, болтовня, шутки
- творчество, написание текста
- мнения, советы

Ответь ровно одним словом: YES или NO. Без объяснений."""


async def _needs_web(text: str) -> bool:
    snippet = (text or "").strip()
    if not snippet:
        return False
    try:
        result = await make_openrouter_query(
            0,
            OpenRouterModel.FAST,
            [("user", _ROUTER_PROMPT.format(query=snippet[:1000]))],
            "",
            max_tokens=4,
            timeout_seconds=8.0,
        )
    except Exception as e:
        logger.warning("ai router classifier failed, defaulting to offline: %s", e)
        return False
    return "yes" in (result or "").strip().lower()[:8]


def _last_user_text(msgs: list[tuple[str, str]]) -> str:
    for role, content in reversed(msgs):
        if role == "user":
            return content
    return ""


def _strip_command_prefix(text: str) -> str:
    stripped = (text or "").lstrip()
    if stripped.startswith("/ai"):
        rest = stripped[3:]
        if rest.startswith("@"):
            space = rest.find(" ")
            rest = rest[space + 1:] if space != -1 else ""
        return rest.strip()
    return stripped


async def _online_aware_placeholder(text: str, needs_web: bool) -> str | None:
    """Pick a fun phrase telling the user whether we're hitting the web."""
    if needs_web:
        return random.choice(_ONLINE_PHRASES)
    return await try_contextual_placeholder(text, _quick_call)


async def _online_stream(uid, msgs):
    return await make_openrouter_stream(
        uid,
        OpenRouterModel.GROK_4_FAST_ONLINE,
        msgs,
        _build_online_system_prompt(),
    )


async def _offline_stream(uid, msgs):
    return await make_text_stream(uid, Model.SMART, msgs, _build_system_prompt())


async def _ai_call(uid, msgs):
    user_text = _last_user_text(msgs)
    if user_text and await _needs_web(user_text):
        logger.info("ai router: routed to :online (non-stream)")
        return await make_openrouter_query(
            uid,
            OpenRouterModel.GROK_4_FAST_ONLINE,
            msgs,
            _build_online_system_prompt(),
        )
    return await make_text_query(uid, Model.SMART, msgs, _build_system_prompt())


async def _ai_stream(uid, msgs):
    user_text = _last_user_text(msgs)
    if user_text and await _needs_web(user_text):
        logger.info(
            "ai router: routed to :online (stream) — caller stack:\n%s",
            "".join(traceback.format_stack()[-6:-1]),
        )
        return await _online_stream(uid, msgs)
    return await _offline_stream(uid, msgs)


async def _quick_call(prompt: str) -> str:
    return await make_text_query(0, Model.FAST, [("user", prompt)], "")


async def _ask_streaming(ctx: FeatureContext, full_text: str):
    """Shared streaming entry for /ai. Classifies online/offline once, then
    feeds the right stream call and a matching placeholder phrase."""
    user_query = _strip_command_prefix(full_text)
    needs_web = bool(user_query) and await _needs_web(user_query)
    if needs_web:
        logger.info("ai router: routed to :online (stream/pre)")

    stream_call = _online_stream if needs_web else _offline_stream

    await execute_ai_request_streaming(
        ctx,
        full_text,
        stream_call,
        "ai",
        quick_call=_quick_call,
        placeholder_upgrade=_online_aware_placeholder(full_text, needs_web),
    )


class AIFeature(Feature):
    command = "ai"
    description = "Поговорить с ИИ"

    @on_init
    async def _set_repo(self):
        _REPO_HOLDER["repo"] = self.repository
        register_ai_handler("ai", _ai_call, _ai_stream, quick_call=_quick_call)
        await ensure_thinking_phrases(
            lambda prompt: make_text_query(0, Model.SMART, [("user", prompt)], "")
        )

    @subcommand("<text:rest>", description="Запрос к ИИ", catchall=True)
    async def ask(self, ctx: FeatureContext, text: str):
        full_text = ctx.message.text if ctx.message else text
        await _ask_streaming(ctx, full_text)

    @subcommand("", description="Без аргументов")
    async def empty(self, ctx: FeatureContext):
        await _ask_streaming(ctx, ctx.message.text or "")

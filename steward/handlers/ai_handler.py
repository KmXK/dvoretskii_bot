from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.ai import GROK_SHORT_AGGRESSIVE, OpenRouterModel, make_openrouter_query
from steward.helpers.ai_context import execute_ai_request, register_ai_handler

_ai_handler_repository = None


def _build_users_descriptions_block() -> str:
    if _ai_handler_repository is None:
        return "- Пока нет описаний."

    descriptions = []
    for user in _ai_handler_repository.db.users:
        if not user.stand_name or not user.stand_description:
            continue
        descriptions.append(
            f"- {user.stand_name.strip()}: {user.stand_description.strip()}",
        )

    if not descriptions:
        return "- Пока нет описаний."
    return "\n".join(descriptions)


def _build_system_prompt() -> str:
    users_descriptions = _build_users_descriptions_block()
    return GROK_SHORT_AGGRESSIVE.replace("{{USERS_DESCRIPTIONS}}", users_descriptions)


def _ai_call(uid, msgs):
    return make_openrouter_query(
        uid,
        OpenRouterModel.GROK_4_FAST,
        msgs,
        _build_system_prompt(),
    )


register_ai_handler("ai", _ai_call)


@CommandHandler("ai")
class AIHandler(Handler):
    async def init(self):
        global _ai_handler_repository
        _ai_handler_repository = self.repository

    async def chat(self, context: ChatBotContext):
        await execute_ai_request(
            context,
            context.message.text,
            _ai_call,
            "ai",
        )
        return True

    def help(self):
        return "/ai - поговорить с ии"

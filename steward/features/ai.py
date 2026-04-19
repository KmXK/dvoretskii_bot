from steward.framework import Feature, FeatureContext, on_init, subcommand
from steward.helpers.ai import GROK_SHORT_AGGRESSIVE, OpenRouterModel, make_openrouter_query
from steward.helpers.ai_context import execute_ai_request, register_ai_handler


_REPO_HOLDER = {"repo": None}


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


def _ai_call(uid, msgs):
    return make_openrouter_query(uid, OpenRouterModel.GROK_4_FAST, msgs, _build_system_prompt())


register_ai_handler("ai", _ai_call)


class AIFeature(Feature):
    command = "ai"
    description = "Поговорить с ИИ"

    @on_init
    async def _set_repo(self):
        _REPO_HOLDER["repo"] = self.repository

    @subcommand("<text:rest>", description="Запрос к ИИ", catchall=True)
    async def ask(self, ctx: FeatureContext, text: str):
        full_text = ctx.message.text if ctx.message else text
        await execute_ai_request(ctx, full_text, _ai_call, "ai")

    @subcommand("", description="Без аргументов")
    async def empty(self, ctx: FeatureContext):
        await execute_ai_request(ctx, ctx.message.text or "", _ai_call, "ai")

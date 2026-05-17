from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.user_language import (
    clear_user_language,
    get_user_language,
    set_user_language,
)


def _resolve_user_id(feature: Feature, identifier: str) -> int | None:
    identifier = identifier.strip().lstrip("@")
    if not identifier:
        return None
    try:
        return int(identifier)
    except ValueError:
        pass
    target = identifier.lower()
    user = next(
        (
            u
            for u in feature.repository.db.users
            if u.username and u.username.lower() == target
        ),
        None,
    )
    return user.id if user else None


class LangFeature(Feature):
    command = "lang"
    only_admin = True
    description = "Языковые оверрайды AI-ответов для конкретных юзеров"
    help_examples = [
        "/lang — текущий список",
        "/lang set @username белорусский",
        "/lang set 430123749 английский",
        "/lang remove @username",
    ]

    @subcommand("", description="Показать все оверрайды")
    async def list_all(self, ctx: FeatureContext):
        overrides = self.repository.db.user_languages
        if not overrides:
            await ctx.reply("Оверрайдов нет")
            return
        lines = ["Языковые оверрайды:", ""]
        for uid_str, lang in sorted(overrides.items()):
            try:
                uid = int(uid_str)
            except ValueError:
                uid = None
            display = f"id{uid_str}"
            if uid is not None:
                user = next(
                    (u for u in self.repository.db.users if u.id == uid), None
                )
                if user:
                    display = (
                        f"@{user.username}" if user.username else (user.first_name or display)
                    )
            lines.append(f"• {display} → {lang}")
        await ctx.reply("\n".join(lines))

    @subcommand("set <user:str> <language:rest>", description="Установить язык юзеру")
    async def set_for(self, ctx: FeatureContext, user: str, language: str):
        uid = _resolve_user_id(self, user)
        if uid is None:
            await ctx.reply(f"Не нашёл юзера {user}")
            return
        language = language.strip()
        if not language:
            await ctx.reply("Укажи название языка")
            return
        set_user_language(self.repository, uid, language)
        await self.repository.save()
        await ctx.reply(f"Готово: id {uid} → {language}")

    @subcommand("remove <user:str>", description="Сбросить оверрайд")
    async def remove(self, ctx: FeatureContext, user: str):
        uid = _resolve_user_id(self, user)
        if uid is None:
            await ctx.reply(f"Не нашёл юзера {user}")
            return
        if not get_user_language(self.repository, uid):
            await ctx.reply("У этого юзера и так нет оверрайда")
            return
        clear_user_language(self.repository, uid)
        await self.repository.save()
        await ctx.reply(f"Оверрайд для id {uid} убран")

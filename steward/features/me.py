import html as html_module

from steward.dynamic_rewards import (
    get_dynamic_reward_holder,
    get_holder_display_name,
)
from steward.framework import (
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    on_callback,
    paginated,
    subcommand,
)
from steward.helpers.emoji import (
    format_lined_list_html,
    format_reward_emoji,
    format_reward_html,
)


class MeFeature(Feature):
    command = "me"
    description = "Профиль пользователя"
    help_examples = [
        "«покажи мой профиль» → /me",
        "«мой профиль» → /me",
    ]

    rewards = collection("rewards")
    user_rewards = collection("user_rewards")
    users = collection("users")

    @subcommand("", description="Показать профиль")
    async def show(self, ctx: FeatureContext):
        text, kb = self._build_profile(ctx.user_id)
        await ctx.reply(text, html=True, markdown=False, keyboard=kb)

    @on_callback("me:rewards", schema="<user_id:int>")
    async def open_rewards(self, ctx: FeatureContext, user_id: int):
        await self.paginate(ctx, "rewards", metadata=str(user_id))

    @on_callback("me:back", schema="<user_id:int>")
    async def go_back(self, ctx: FeatureContext, user_id: int):
        text, kb = self._build_profile(user_id)
        await ctx.edit(text, keyboard=kb, html=True, markdown=False)

    @paginated("rewards", per_page=10, header="Ваши достижения", parse_mode="HTML")
    def rewards_page(self, ctx: FeatureContext, metadata: str):
        user_id = int(metadata)
        rewards_map = {r.id: r for r in self.rewards}
        items = [
            rewards_map[ur.reward_id]
            for ur in self.user_rewards
            if ur.user_id == user_id and ur.reward_id in rewards_map
        ]

        def render(batch):
            entries: list[tuple[int, str]] = []
            for r in batch:
                text = format_reward_html(r)
                if r.dynamic_key:
                    holder_id = get_dynamic_reward_holder(self.repository, r)
                    if holder_id is not None:
                        name = get_holder_display_name(self.repository, holder_id)
                        text += f" → <code>{html_module.escape(name)}</code>"
                    else:
                        text += " → <i>нет владельца</i>"
                entries.append((r.id, text))
            return format_lined_list_html(items=entries, delimiter=". ")

        extra = Keyboard.row(self.cb("me:back").button("← Назад", user_id=user_id))
        return items, render, extra

    def _build_profile(self, user_id: int) -> tuple[str, Keyboard]:
        rewards_map = {r.id: r for r in self.rewards}
        user_reward_ids = [
            ur.reward_id for ur in self.user_rewards if ur.user_id == user_id
        ]
        user_rewards = [rewards_map[rid] for rid in user_reward_ids if rid in rewards_map]
        emojis = (
            " ".join(format_reward_emoji(r) for r in user_rewards) if user_rewards else "нет"
        )
        user = self.users.find_by(id=user_id)
        monkeys = user.monkeys if user else 0
        stand = "нет"
        if user and user.stand_name and user.stand_description:
            stand_name = html_module.escape(user.stand_name)
            stand_description = html_module.escape(user.stand_description)
            stand = f"{stand_name}: {stand_description}"
        text = f"Профиль\n\n🐵 Обезьянки: {monkeys}\nПользователь: {stand}\nДостижения: {emojis}"
        kb = Keyboard.row(self.cb("me:rewards").button("Достижения", user_id=user_id))
        return text, kb

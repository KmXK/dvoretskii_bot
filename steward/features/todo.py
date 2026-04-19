from steward.data.models.reward import Reward, UserReward
from steward.data.models.todo_item import TodoItem
from steward.framework import (
    Feature,
    FeatureContext,
    Keyboard,
    ask,
    collection,
    on_callback,
    paginated,
    subcommand,
    wizard,
)
from steward.helpers.emoji import extract_emoji, format_reward_html
from steward.helpers.formats import format_lined_list
from steward.helpers.tg_update_helpers import get_message
from steward.helpers.validation import check, try_get, validate_message_text


class TodoFeature(Feature):
    command = "todo"
    description = "События / задачи в чате"
    help_examples = [
        "«добавь в туду купить молоко» → /todo купить молоко",
        "«отметь задачу 3 выполненной» → /todo done 3",
        "«удали задачу 5» → /todo remove 5",
        "«покажи список дел» → /todo",
    ]

    todos = collection("todo_items")
    rewards = collection("rewards")
    user_rewards = collection("user_rewards")
    users = collection("users")

    @subcommand("", description="Список")
    async def list_default(self, ctx: FeatureContext):
        await self.paginate(ctx, "todos", metadata=str(ctx.chat_id))

    @subcommand("list", description="Список")
    async def list_alias(self, ctx: FeatureContext):
        await self.paginate(ctx, "todos", metadata=str(ctx.chat_id))

    @subcommand("done <id:int>", description="Отметить выполненным")
    async def done(self, ctx: FeatureContext, id: int):
        todo = self.todos.find_by(id=id, chat_id=ctx.chat_id)
        if todo is None:
            await ctx.reply("Событие не найдено")
            return
        if todo.is_done:
            await ctx.reply("Событие уже завершено")
            return
        todo.is_done = True
        await self.todos.save()
        kb = Keyboard.row(
            self.cb("todo:reward").button("Да",  answer="yes", todo_id=id, initiator=ctx.user_id),
            self.cb("todo:reward").button("Нет", answer="no",  todo_id=id, initiator=ctx.user_id),
        )
        await ctx.reply(
            f'Событие "{todo.text}" завершено!\n\nХотите добавить достижение?',
            keyboard=kb,
        )

    @subcommand("remove <id:int>", description="Удалить")
    async def remove(self, ctx: FeatureContext, id: int):
        todo = self.todos.find_by(id=id, chat_id=ctx.chat_id)
        if todo is None:
            await ctx.reply("Событие не найдено")
            return
        self.todos.remove(todo)
        await self.todos.save()
        await ctx.reply(f'Событие "{todo.text}" удалено')

    @subcommand("<text:rest>", description="Добавить событие", catchall=True)
    async def add(self, ctx: FeatureContext, text: str):
        todo = self.todos.add(TodoItem(id=0, chat_id=ctx.chat_id, text=text))
        await self.todos.save()
        await ctx.reply(f"Событие добавлено (id: {todo.id})")

    @on_callback(
        "todo:reward",
        schema="<answer:literal[yes|no]>|<todo_id:int>|<initiator:int>",
        only_initiator=True,
    )
    async def on_reward(
        self, ctx: FeatureContext, answer: str, todo_id: int, initiator: int
    ):
        if answer == "no":
            await ctx.delete_or_clear_keyboard()
            return
        try:
            await ctx.callback_query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await self.start_wizard("todo:ask_reward", ctx, todo_id=todo_id)

    @paginated("todos", per_page=10, header="Список событий")
    def todos_page(self, ctx: FeatureContext, metadata: str):
        chat_id = int(metadata)
        items = [t for t in self.todos if t.chat_id == chat_id and not t.is_done]
        render = lambda batch: format_lined_list(
            items=[(t.id, t.text) for t in batch], delimiter=". "
        )
        return items, render

    @wizard(
        "todo:ask_reward",
        ask("reward_name", "Название достижения", validator=validate_message_text([])),
        ask("reward_emoji", "Эмоджи достижения", validator=extract_emoji),
        ask(
            "reward_users",
            "Кому присвоить? (username или id через пробел)",
            validator=validate_message_text([
                try_get(lambda t: t.split()),
                check(lambda ids: len(ids) > 0, "Укажите хотя бы одного пользователя"),
            ]),
        ),
    )
    async def on_wizard_done(self, ctx: FeatureContext, **state):
        emoji_data = state["reward_emoji"]
        reward = self.rewards.add(Reward(
            id=0,
            name=state["reward_name"],
            emoji=emoji_data["text"],
            custom_emoji_id=emoji_data["custom_emoji_id"],
        ))
        assigned = 0
        for identifier in state["reward_users"]:
            user = self._resolve_user(identifier)
            if user is not None:
                self.user_rewards.add(UserReward(user_id=user.id, reward_id=reward.id))
                assigned += 1
        await self.rewards.save()
        message = get_message(ctx.update)
        await message.chat.send_message(
            f"Достижение {format_reward_html(reward)} создано и вручено ({assigned})",
            parse_mode="HTML",
        )

    def _resolve_user(self, identifier: str):
        identifier = identifier.lstrip("@")
        try:
            return self.users.find_by(id=int(identifier))
        except ValueError:
            pass
        target = identifier.lower()
        return self.users.find_one(
            lambda u: u.username and u.username.lower() == target
        )

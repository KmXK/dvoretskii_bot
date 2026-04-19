"""End-to-end Feature dispatch tests."""
from steward.framework import (
    Feature,
    FeatureContext,
    on_callback,
    subcommand,
)
from tests.conftest import make_context, make_repository


class _Echo(Feature):
    command = "echo"
    description = "Echo test"
    received: list[tuple[str, dict]] = []

    @subcommand("", description="empty")
    async def empty(self, ctx: FeatureContext):
        self.received.append(("empty", {}))

    @subcommand("greet <name:str>", description="greet")
    async def greet(self, ctx: FeatureContext, name: str):
        self.received.append(("greet", {"name": name}))

    @subcommand("add <a:int> <b:int>", description="add")
    async def add(self, ctx: FeatureContext, a: int, b: int):
        self.received.append(("add", {"a": a, "b": b}))

    @subcommand("punishment add <coeff:int> <title:rest>", description="multi-literal")
    async def punishment_add(self, ctx: FeatureContext, coeff: int, title: str):
        self.received.append(("punishment_add", {"coeff": coeff, "title": title}))

    @subcommand("<text:rest>", description="catchall", catchall=True)
    async def catchall(self, ctx: FeatureContext, text: str):
        self.received.append(("catchall", {"text": text}))


async def test_empty_subcommand():
    f = _Echo()
    f.repository = make_repository()
    f.received = []
    ctx = make_context("echo")
    assert await f.chat(ctx) is True
    assert f.received == [("empty", {})]


async def test_typed_args():
    f = _Echo()
    f.repository = make_repository()
    f.received = []
    ctx = make_context("echo", "add 2 3")
    assert await f.chat(ctx) is True
    assert f.received == [("add", {"a": 2, "b": 3})]


async def test_multi_literal_with_typed():
    f = _Echo()
    f.repository = make_repository()
    f.received = []
    ctx = make_context("echo", "punishment add 5 отжимания утром")
    assert await f.chat(ctx) is True
    assert f.received == [
        ("punishment_add", {"coeff": 5, "title": "отжимания утром"})
    ]


async def test_catchall():
    f = _Echo()
    f.repository = make_repository()
    f.received = []
    ctx = make_context("echo", "купить молоко")
    assert await f.chat(ctx) is True
    assert f.received == [("catchall", {"text": "купить молоко"})]


async def test_priority_typed_before_catchall():
    f = _Echo()
    f.repository = make_repository()
    f.received = []
    ctx = make_context("echo", "greet alice")
    assert await f.chat(ctx) is True
    assert f.received == [("greet", {"name": "alice"})]


async def test_unrelated_command_ignored():
    f = _Echo()
    f.repository = make_repository()
    f.received = []
    ctx = make_context("other")
    assert await f.chat(ctx) is False
    assert f.received == []


async def test_help_autogen_starts_with_command():
    f = _Echo()
    h = f.help()
    assert h is not None
    assert h.startswith("/echo")


async def test_prompt_autogen():
    f = _Echo()
    p = f.prompt()
    assert p is not None
    assert "/echo" in p


class _CbFeature(Feature):
    command = "cb"
    received: list[dict] = []

    @on_callback("cb:do", schema="<answer:literal[yes|no]>|<id:int>")
    async def on_do(self, ctx, answer, id):
        self.received.append({"answer": answer, "id": id})

    @subcommand("", description="show")
    async def show(self, ctx):
        pass


async def test_callback_factory_serialize():
    f = _CbFeature()
    factory = f.cb("cb:do")
    btn = factory.button("Yes", answer="yes", id=42)
    assert btn.callback_data == "cb:do|yes|42"


async def test_callback_dispatch():
    from unittest.mock import MagicMock

    from steward.bot.context import CallbackBotContext

    f = _CbFeature()
    f.repository = make_repository()
    f.received = []

    callback_query = MagicMock()
    callback_query.data = "cb:do|yes|42"
    callback_query.from_user.id = 12345
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = None
    update.callback_query = callback_query
    update.effective_message = MagicMock()
    update.effective_message.chat.id = -1

    ctx = CallbackBotContext(
        repository=f.repository,
        bot=MagicMock(),
        client=MagicMock(),
        update=update,
        tg_context=MagicMock(),
        metrics=MagicMock(),
        callback_query=callback_query,
    )
    handled = await f.callback(ctx)
    assert handled is True
    assert f.received == [{"answer": "yes", "id": 42}]


from steward.framework import on_message, on_reaction


class _MultiMsg(Feature):
    log: list[str] = []

    @on_message
    async def zebra(self, ctx):
        self.log.append("zebra")
        return False

    @on_message
    async def alpha(self, ctx):
        self.log.append("alpha")
        return False

    @on_message
    async def middle(self, ctx):
        self.log.append("middle")
        return False


def test_on_message_uses_definition_order():
    f = _MultiMsg()
    names = [h.__name__ for h in f._on_message_handlers]
    assert names == ["zebra", "alpha", "middle"]


class _StopAfterFirst(Feature):
    log: list[str] = []

    @on_message
    async def first(self, ctx):
        self.log.append("first")
        return True

    @on_message
    async def second(self, ctx):
        self.log.append("second")
        return False


async def test_on_message_first_true_stops():
    from tests.conftest import make_text_context

    f = _StopAfterFirst()
    f.repository = make_repository()
    f.log = []
    ctx = make_text_context("hi")
    await f.chat(ctx)
    assert f.log == ["first"]


class _MultiReaction(Feature):
    log: list[str] = []

    @on_reaction
    async def b_handler(self, ctx):
        self.log.append("b")
        return False

    @on_reaction
    async def a_handler(self, ctx):
        self.log.append("a")
        return True


async def test_on_reaction_definition_order_first_true_stops():
    from unittest.mock import MagicMock

    from steward.bot.context import ReactionBotContext

    f = _MultiReaction()
    f.repository = make_repository()
    f.log = []
    update = MagicMock()
    update.effective_user.id = 12345
    update.message = None
    update.callback_query = None
    update.effective_message = MagicMock()
    update.effective_message.chat.id = -1
    update.message_reaction = MagicMock()
    ctx = ReactionBotContext(
        repository=f.repository,
        bot=MagicMock(),
        client=MagicMock(),
        update=update,
        tg_context=MagicMock(),
        metrics=MagicMock(),
        message_reaction=update.message_reaction,
    )
    handled = await f.reaction(ctx)
    assert handled is True
    assert f.log == ["b", "a"]

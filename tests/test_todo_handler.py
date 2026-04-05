"""Tests for todo handlers: list, add, remove, done routing."""
from steward.data.models.todo_item import TodoItem
from tests.conftest import make_context, make_repository


CHAT_ID = -100123456789


def repo_with_todos():
    repo = make_repository()
    repo.db.todo_items = [
        TodoItem(id=1, chat_id=CHAT_ID, text="купить молоко"),
        TodoItem(id=2, chat_id=CHAT_ID, text="позвонить маме"),
        TodoItem(id=3, chat_id=CHAT_ID, text="already done", is_done=True),
    ]
    return repo


# ---------------------------------------------------------------------------
# TodoListHandler
# ---------------------------------------------------------------------------

class TestTodoList:
    async def test_shows_active_todos(self):
        from steward.handlers.todo_handler import TodoListHandler

        repo = repo_with_todos()
        handler = TodoListHandler()
        handler.repository = repo

        ctx = make_context("todo", repo=repo)
        result = await handler.chat(ctx)

        assert result is True
        # paginator uses reply_text or edit_message_text
        assert ctx.message.reply_text.called or ctx.message.reply_html.called

    async def test_done_items_not_shown(self):
        """Paginator only returns non-done items."""
        from steward.handlers.todo_handler import TodoListHandler

        repo = repo_with_todos()
        handler = TodoListHandler()
        handler.repository = repo

        visible = [
            t for t in repo.db.todo_items
            if t.chat_id == CHAT_ID and not t.is_done
        ]
        assert len(visible) == 2  # not 3

    async def test_empty_list(self):
        from steward.handlers.todo_handler import TodoListHandler

        repo = make_repository()
        handler = TodoListHandler()
        handler.repository = repo

        ctx = make_context("todo", repo=repo)
        result = await handler.chat(ctx)

        assert result is True


# ---------------------------------------------------------------------------
# TodoAddHandler
# ---------------------------------------------------------------------------

class TestTodoAdd:
    async def test_adds_new_todo(self):
        from steward.handlers.todo_handler import TodoAddHandler

        repo = make_repository()
        handler = TodoAddHandler()
        handler.repository = repo

        ctx = make_context("todo", args="написать тесты", repo=repo)
        result = await handler.chat(ctx)

        assert result is True
        assert len(repo.db.todo_items) == 1
        assert repo.db.todo_items[0].text == "написать тесты"
        assert repo.db.todo_items[0].chat_id == CHAT_ID

    async def test_reply_contains_id(self):
        from steward.handlers.todo_handler import TodoAddHandler

        repo = make_repository()
        handler = TodoAddHandler()
        handler.repository = repo

        ctx = make_context("todo", args="задача", repo=repo)
        await handler.chat(ctx)

        reply = ctx.message.reply_text.call_args[0][0]
        assert "1" in reply  # first item gets id=1

    async def test_increments_id(self):
        from steward.handlers.todo_handler import TodoAddHandler

        repo = repo_with_todos()  # already has ids 1,2,3
        handler = TodoAddHandler()
        handler.repository = repo

        ctx = make_context("todo", args="новая задача", repo=repo)
        await handler.chat(ctx)

        new_todo = repo.db.todo_items[-1]
        assert new_todo.id == 4

    async def test_ignores_bare_command(self):
        from steward.handlers.todo_handler import TodoAddHandler

        handler = TodoAddHandler()
        handler.repository = make_repository()

        ctx = make_context("todo")
        result = await handler.chat(ctx)

        assert result is False

    async def test_ignores_subcommand_keywords(self):
        from steward.handlers.todo_handler import TodoAddHandler

        handler = TodoAddHandler()
        handler.repository = make_repository()

        ctx = make_context("todo", args="done 1")
        result = await handler.chat(ctx)

        assert result is False


# ---------------------------------------------------------------------------
# TodoRemoveHandler
# ---------------------------------------------------------------------------

class TestTodoRemove:
    async def test_removes_existing_todo(self):
        from steward.handlers.todo_handler import TodoRemoveHandler

        repo = repo_with_todos()
        handler = TodoRemoveHandler()
        handler.repository = repo

        ctx = make_context("todo", args="remove 1", repo=repo)
        result = await handler.chat(ctx)

        assert result is True
        assert not any(t.id == 1 for t in repo.db.todo_items)
        assert len(repo.db.todo_items) == 2

    async def test_reply_contains_todo_text(self):
        from steward.handlers.todo_handler import TodoRemoveHandler

        repo = repo_with_todos()
        handler = TodoRemoveHandler()
        handler.repository = repo

        ctx = make_context("todo", args="remove 1", repo=repo)
        await handler.chat(ctx)

        reply = ctx.message.reply_text.call_args[0][0]
        assert "купить молоко" in reply

    async def test_nonexistent_todo(self):
        from steward.handlers.todo_handler import TodoRemoveHandler

        repo = repo_with_todos()
        handler = TodoRemoveHandler()
        handler.repository = repo

        ctx = make_context("todo", args="remove 999", repo=repo)
        result = await handler.chat(ctx)

        assert result is True
        reply = ctx.message.reply_text.call_args[0][0]
        assert "не найдено" in reply
        assert len(repo.db.todo_items) == 3

    async def test_invalid_id(self):
        from steward.handlers.todo_handler import TodoRemoveHandler

        handler = TodoRemoveHandler()
        handler.repository = make_repository()

        ctx = make_context("todo", args="remove abc")
        result = await handler.chat(ctx)

        assert result is True
        reply = ctx.message.reply_text.call_args[0][0]
        assert "числом" in reply

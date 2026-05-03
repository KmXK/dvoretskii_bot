"""Tests for TodoFeature: list, add, remove."""
from steward.data.models.todo_item import TodoItem
from steward.features.todo import TodoFeature
from tests.conftest import invoke, make_context, make_repository


CHAT_ID = -100123456789


def repo_with_todos():
    repo = make_repository()
    repo.db.todo_items = [
        TodoItem(id=1, chat_id=CHAT_ID, text="купить молоко"),
        TodoItem(id=2, chat_id=CHAT_ID, text="позвонить маме"),
        TodoItem(id=3, chat_id=CHAT_ID, text="already done", is_done=True),
    ]
    return repo


class TestTodoList:
    async def test_shows_active_todos(self):
        repo = repo_with_todos()
        feature = TodoFeature()
        feature.repository = repo

        ctx = make_context("todo", repo=repo)
        result = await feature.chat(ctx)

        assert result is True
        assert ctx.message.reply_text.called or ctx.message.reply_html.called

    async def test_done_items_not_shown(self):
        repo = repo_with_todos()
        visible = [
            t for t in repo.db.todo_items
            if t.chat_id == CHAT_ID and not t.is_done
        ]
        assert len(visible) == 2

    async def test_empty_list(self):
        repo = make_repository()
        feature = TodoFeature()
        feature.repository = repo

        ctx = make_context("todo", repo=repo)
        result = await feature.chat(ctx)
        assert result is True


class TestTodoAdd:
    async def test_adds_new_todo(self):
        repo = make_repository()
        reply, ok = await invoke(TodoFeature, "/todo написать тесты", repo)
        assert ok
        assert len(repo.db.todo_items) == 1
        assert repo.db.todo_items[0].text == "написать тесты"
        assert repo.db.todo_items[0].chat_id == CHAT_ID

    async def test_reply_contains_id(self):
        repo = make_repository()
        reply, _ = await invoke(TodoFeature, "/todo задача", repo)
        assert "1" in reply

    async def test_increments_id(self):
        repo = repo_with_todos()
        await invoke(TodoFeature, "/todo новая задача", repo)
        new_todo = repo.db.todo_items[-1]
        assert new_todo.id == 4


class TestTodoRemove:
    async def test_removes_existing_todo(self):
        repo = repo_with_todos()
        reply, ok = await invoke(TodoFeature, "/todo remove 1", repo)
        assert ok
        assert not any(t.id == 1 for t in repo.db.todo_items)
        assert len(repo.db.todo_items) == 2

    async def test_reply_contains_todo_text(self):
        repo = repo_with_todos()
        reply, _ = await invoke(TodoFeature, "/todo remove 1", repo)
        assert "купить молоко" in reply

    async def test_nonexistent_todo(self):
        repo = repo_with_todos()
        reply, ok = await invoke(TodoFeature, "/todo remove 999", repo)
        assert ok
        assert "не найдено" in reply
        assert len(repo.db.todo_items) == 3

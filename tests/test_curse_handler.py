from unittest.mock import MagicMock

from tests.conftest import DEFAULT_USER_ID, invoke, make_repository


class TestCurseWordListViewHandler:
    async def test_empty_list(self):
        from steward.handlers.curse_handler import CurseWordListViewHandler

        reply, ok = await invoke(CurseWordListViewHandler, "/curse word_list", make_repository())
        assert ok
        assert "пуст" in reply.lower()

    async def test_shows_sorted_words(self):
        from steward.handlers.curse_handler import CurseWordListViewHandler

        repo = make_repository()
        repo.db.curse_words = {"б", "а"}
        reply, ok = await invoke(CurseWordListViewHandler, "/curse word_list", repo)
        assert ok
        assert "Матерные слова:" in reply
        assert reply.index("а") < reply.index("б")


class TestCurseWordListAddHandler:
    async def test_adds_only_new_words_in_lowercase(self):
        from steward.handlers.curse_handler import CurseWordListAddHandler

        repo = make_repository()
        repo.db.curse_words = {"старое"}
        reply, ok = await invoke(
            CurseWordListAddHandler,
            "/curse word_list add Старое Новое НОВОЕ",
            repo,
        )
        assert ok
        assert repo.db.curse_words == {"старое", "новое"}
        assert "новое" in reply
        assert "старое" not in reply

    async def test_reports_when_all_words_already_exist(self):
        from steward.handlers.curse_handler import CurseWordListAddHandler

        repo = make_repository()
        repo.db.curse_words = {"слово"}
        reply, ok = await invoke(CurseWordListAddHandler, "/curse word_list add СЛОВО", repo)
        assert ok
        assert "уже есть" in reply.lower()


class TestCurseWordListRemoveHandler:
    async def test_removes_existing_words(self):
        from steward.handlers.curse_handler import CurseWordListRemoveHandler

        repo = make_repository()
        repo.db.curse_words = {"одно", "два"}
        reply, ok = await invoke(CurseWordListRemoveHandler, "/curse word_list remove ОДНО три", repo)
        assert ok
        assert repo.db.curse_words == {"два"}
        assert "одно" in reply

    async def test_reports_when_nothing_removed(self):
        from steward.handlers.curse_handler import CurseWordListRemoveHandler

        reply, ok = await invoke(
            CurseWordListRemoveHandler,
            "/curse word_list remove неттакого",
            make_repository(),
        )
        assert ok
        assert "не найдено" in reply.lower()


def test_admin_restrictions_are_declared():
    from steward.handlers.curse_handler import CurseWordListAddHandler, CurseWordListRemoveHandler, CurseWordListViewHandler

    assert CurseWordListViewHandler.only_for_admin is False
    assert CurseWordListAddHandler.only_for_admin is True
    assert CurseWordListRemoveHandler.only_for_admin is True

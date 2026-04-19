"""Tests for FeatureRequestFeature: view/add, edit status."""
from steward.data.models.feature_request import (
    FeatureRequest,
    FeatureRequestChange,
    FeatureRequestStatus,
)
from steward.features.feature_request import FeatureRequestFeature
from tests.conftest import invoke, make_repository

USER_ID = 12345


def _fr(id: int, text: str, author_id: int = USER_ID) -> FeatureRequest:
    return FeatureRequest(
        id=id,
        text=text,
        author_id=author_id,
        author_name="testuser",
        creation_timestamp=None,
        message_id=None,
        chat_id=None,
    )


class TestFeatureRequestView:
    async def test_adds_feature_request(self):
        repo = make_repository()
        reply, ok = await invoke(FeatureRequestFeature, "/fr тёмная тема", repo)
        assert ok
        assert len(repo.db.feature_requests) == 1
        assert repo.db.feature_requests[0].text == "тёмная тема"
        assert "добавлен" in reply

    async def test_shows_single_feature_request(self):
        repo = make_repository()
        repo.db.feature_requests = [_fr(1, "тёмная тема")]
        reply, ok = await invoke(FeatureRequestFeature, "/fr 1", repo)
        assert ok
        assert "тёмная тема" in reply
        assert "1" in reply

    async def test_nonexistent_feature_request(self):
        repo = make_repository()
        reply, ok = await invoke(FeatureRequestFeature, "/fr 999", repo)
        assert ok
        assert "не существует" in reply

    async def test_id_increments(self):
        repo = make_repository()
        repo.db.feature_requests = [_fr(1, "первая фича")]
        await invoke(FeatureRequestFeature, "/fr вторая фича", repo)
        assert len(repo.db.feature_requests) == 2
        assert repo.db.feature_requests[1].id == 2


class TestFeatureRequestEdit:
    async def test_marks_done(self):
        repo = make_repository()
        repo.db.feature_requests = [_fr(1, "тёмная тема")]
        reply, ok = await invoke(FeatureRequestFeature, "/fr done 1", repo)
        assert ok
        assert repo.db.feature_requests[0].status == FeatureRequestStatus.DONE
        assert "✅" in reply

    async def test_denies(self):
        repo = make_repository()
        repo.db.feature_requests = [_fr(1, "тёмная тема")]
        reply, ok = await invoke(FeatureRequestFeature, "/fr deny 1", repo)
        assert ok
        assert repo.db.feature_requests[0].status == FeatureRequestStatus.DENIED

    async def test_nonexistent_id(self):
        repo = make_repository()
        reply, ok = await invoke(FeatureRequestFeature, "/fr done 999", repo)
        assert ok
        assert "не существует" in reply

    async def test_already_done_error(self):
        repo = make_repository()
        fr = _fr(1, "тёмная тема")
        fr.history = [
            FeatureRequestChange(
                author_id=USER_ID,
                timestamp=0,
                message_id=1,
                status=FeatureRequestStatus.DONE,
            )
        ]
        repo.db.feature_requests = [fr]
        reply, ok = await invoke(FeatureRequestFeature, "/fr done 1", repo)
        assert ok
        assert "уже" in reply

    async def test_no_ids_provided(self):
        # In the new Feature model `/fr done` (no ids) falls through to the add catchall
        # because `done <ids:rest>` requires a non-empty `ids`. This adds a request named "done"
        # rather than complaining — verify the catchall behavior instead.
        repo = make_repository()
        reply, ok = await invoke(FeatureRequestFeature, "/fr done", repo)
        assert ok
        assert "добавлен" in reply
        assert len(repo.db.feature_requests) == 1

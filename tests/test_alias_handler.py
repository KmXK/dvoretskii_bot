"""Tests for AliasFeature: management commands + trigger expansion."""
from steward.data.models.command_alias import CommandAlias
from steward.features.alias import AliasFeature
from tests.conftest import (
    CHAT_ID,
    invoke,
    make_repository,
    make_text_context,
)


def repo_with_alias(trigger="#done", expansion="/curse done 1 100", chat_id=CHAT_ID):
    repo = make_repository()
    repo.db.command_aliases = [
        CommandAlias(chat_id=chat_id, trigger=trigger, expansion=expansion, created_by=1)
    ]
    return repo


class TestAliasManagement:
    async def test_add_alias(self):
        repo = make_repository()
        reply, ok = await invoke(AliasFeature, "/alias add #done /curse done 1 100", repo)
        assert ok
        assert "добавлен" in reply
        stored = repo.db.command_aliases
        assert len(stored) == 1
        assert stored[0].trigger == "#done"
        assert stored[0].expansion == "/curse done 1 100"
        assert stored[0].chat_id == CHAT_ID

    async def test_add_overwrites_existing(self):
        repo = repo_with_alias()
        reply, ok = await invoke(AliasFeature, "/alias add #done /curse done 5 500", repo)
        assert ok
        assert "обновлён" in reply
        assert len(repo.db.command_aliases) == 1
        assert repo.db.command_aliases[0].expansion == "/curse done 5 500"

    async def test_cannot_alias_itself(self):
        repo = make_repository()
        reply, ok = await invoke(AliasFeature, "/alias add /alias /curse done 1 100", repo)
        assert ok
        assert "Нельзя" in reply
        assert len(repo.db.command_aliases) == 0

    async def test_plain_text_expansion_warns(self):
        repo = make_repository()
        reply, ok = await invoke(AliasFeature, "/alias add #hi привет всем", repo)
        assert ok
        assert "⚠️" in reply
        assert repo.db.command_aliases[0].expansion == "привет всем"

    async def test_list_empty(self):
        reply, ok = await invoke(AliasFeature, "/alias", make_repository())
        assert ok
        assert "нет алиасов" in reply

    async def test_list_shows_aliases(self):
        reply, ok = await invoke(AliasFeature, "/alias", repo_with_alias())
        assert ok
        assert "#done" in reply
        assert "/curse done 1 100" in reply

    async def test_remove_alias(self):
        repo = repo_with_alias()
        reply, ok = await invoke(AliasFeature, "/alias remove #done", repo)
        assert ok
        assert "удалён" in reply
        assert len(repo.db.command_aliases) == 0

    async def test_remove_alt_rm(self):
        repo = repo_with_alias()
        reply, ok = await invoke(AliasFeature, "/alias rm #done", repo)
        assert ok
        assert "удалён" in reply
        assert len(repo.db.command_aliases) == 0

    async def test_remove_nonexistent(self):
        repo = repo_with_alias()
        reply, ok = await invoke(AliasFeature, "/alias remove #nope", repo)
        assert ok
        assert "нет" in reply
        assert len(repo.db.command_aliases) == 1


class TestAliasExpansion:
    async def _expand(self, repo, text):
        handler = AliasFeature()
        handler.repository = repo
        ctx = make_text_context(text, repo=repo)
        handled = await handler.chat(ctx)
        return ctx.message, handled

    async def test_exact_trigger_expands(self):
        msg, handled = await self._expand(repo_with_alias(), "#done")
        # on_message expansion lets the pipeline continue → returns falsy
        assert not handled
        assert msg.text == "/curse done 1 100"
        assert msg.entities[0].type == "bot_command"

    async def test_trailing_args_appended(self):
        repo = repo_with_alias(trigger="#fine", expansion="/curse done")
        msg, _ = await self._expand(repo, "#fine 1 100")
        assert msg.text == "/curse done 1 100"

    async def test_args_placeholder_substituted(self):
        repo = repo_with_alias(trigger="#fine", expansion="/curse done {args}")
        msg, _ = await self._expand(repo, "#fine 1 100")
        assert msg.text == "/curse done 1 100"

    async def test_case_insensitive_trigger(self):
        msg, _ = await self._expand(repo_with_alias(trigger="#Done"), "#done")
        assert msg.text == "/curse done 1 100"

    async def test_unknown_trigger_untouched(self):
        msg, handled = await self._expand(repo_with_alias(), "#other")
        assert not handled
        assert msg.text == "#other"

    async def test_slash_message_ignored(self):
        msg, handled = await self._expand(repo_with_alias(trigger="/done"), "/done now")
        assert not handled
        assert msg.text == "/done now"

    async def test_other_chat_not_matched(self):
        repo = repo_with_alias(chat_id=-999)
        msg, handled = await self._expand(repo, "#done")
        assert not handled
        assert msg.text == "#done"

    async def test_plain_text_expansion_no_command_entity(self):
        repo = repo_with_alias(trigger="#hi", expansion="привет всем")
        msg, _ = await self._expand(repo, "#hi")
        assert msg.text == "привет всем"
        assert msg.entities == ()

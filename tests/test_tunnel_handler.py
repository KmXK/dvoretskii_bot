"""Tests for TunnelFeature: open/close, connect, accept/decline, send, replies, remove."""
from unittest.mock import AsyncMock, MagicMock

from telegram import Update

from steward.data.models.chat import Chat
from steward.data.models.chat_tunnel import ChatTunnel, TunnelMessage
from steward.data.models.user import User
from steward.features.tunnel import TunnelFeature
from steward.framework import FeatureContext
from tests.conftest import (
    get_reply_text,
    make_bot,
    make_context,
    make_repository,
    make_text_update,
)


def reply_of(ctx) -> str:
    return get_reply_text(ctx.message.reply_text)

CHAT_A = -100111
CHAT_B = -100222
USER = 777
ADMIN = 999


def base_repo() -> "object":
    repo = make_repository()
    repo.db.chats = [
        Chat(id=CHAT_A, name="Чат А"),
        Chat(id=CHAT_B, name="Чат Б"),
    ]
    repo.db.users = [
        User(USER, "user", [CHAT_A], first_name="Юзер"),
        User(ADMIN, "admin", [CHAT_B], first_name="Админ"),
    ]
    return repo


def make_admin(repo, user_id: int, chat_id: int) -> None:
    repo.chat_settings_for(chat_id).chat_admins.add(user_id)


def make_feature(repo, bot=None) -> TunnelFeature:
    f = TunnelFeature()
    f.repository = repo
    f.bot = bot or MagicMock()
    return f


def make_cb_ctx(repo, bot, user_id: int, chat_id: int) -> FeatureContext:
    update = MagicMock(spec=Update)
    update.message = None
    update.edited_message = None
    cq = MagicMock()
    cq.from_user.id = user_id
    cq.message.chat.id = chat_id
    cq.edit_message_text = AsyncMock()
    cq.answer = AsyncMock()
    update.callback_query = cq
    return FeatureContext(
        update=update,
        tg_context=MagicMock(),
        repository=repo,
        bot=bot,
        client=MagicMock(),
        metrics=MagicMock(),
        callback_query=cq,
    )


class TestOpenClose:
    async def test_open_requires_chat_admin(self):
        repo = base_repo()
        feature = make_feature(repo)
        ctx = make_context("tunnel", args="open", repo=repo, user_id=USER, chat_id=CHAT_B)
        await feature.chat(ctx)
        assert CHAT_B not in repo.db.tunnel_open_chats
        assert "чатадмин" in reply_of(ctx).lower()

    async def test_admin_opens_chat(self):
        repo = base_repo()
        make_admin(repo, ADMIN, CHAT_B)
        feature = make_feature(repo)
        ctx = make_context("tunnel", args="open", repo=repo, user_id=ADMIN, chat_id=CHAT_B)
        result = await feature.chat(ctx)
        assert result is True
        assert CHAT_B in repo.db.tunnel_open_chats

    async def test_close_removes_open(self):
        repo = base_repo()
        make_admin(repo, ADMIN, CHAT_B)
        repo.db.tunnel_open_chats.add(CHAT_B)
        feature = make_feature(repo)
        ctx = make_context("tunnel", args="close", repo=repo, user_id=ADMIN, chat_id=CHAT_B)
        await feature.chat(ctx)
        assert CHAT_B not in repo.db.tunnel_open_chats


class TestConnect:
    async def test_to_lists_open_candidates(self):
        repo = base_repo()
        repo.db.tunnel_open_chats.add(CHAT_B)
        feature = make_feature(repo)
        ctx = make_context("tunnel", args="to", repo=repo, user_id=USER, chat_id=CHAT_A)
        result = await feature.chat(ctx)
        assert result is True
        # keyboard with one button for CHAT_B
        kwargs = ctx.message.reply_text.call_args.kwargs
        assert kwargs.get("reply_markup") is not None

    async def test_to_excludes_self_and_connected(self):
        repo = base_repo()
        repo.db.tunnel_open_chats.add(CHAT_A)  # self — excluded
        repo.db.tunnel_open_chats.add(CHAT_B)
        repo.db.chat_tunnels.append(
            ChatTunnel(id=1, chat_a=CHAT_A, chat_b=CHAT_B, chat_a_name="А", chat_b_name="Б", created_by=USER)
        )
        feature = make_feature(repo)
        candidates = feature._candidate_open_chats(CHAT_A)
        assert candidates == []

    async def test_to_no_candidates_hint(self):
        repo = base_repo()
        feature = make_feature(repo)
        ctx = make_context("tunnel", args="to", repo=repo, user_id=USER, chat_id=CHAT_A)
        await feature.chat(ctx)
        assert "/tunnel open" in reply_of(ctx)


class TestAcceptDecline:
    async def test_accept_requires_target_admin(self):
        repo = base_repo()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_cb_ctx(repo, bot, user_id=USER, chat_id=CHAT_B)
        await feature.on_accept(ctx, from_chat=CHAT_A, to_chat=CHAT_B, by=USER)
        assert repo.db.chat_tunnels == []
        ctx.callback_query.answer.assert_awaited()

    async def test_admin_accept_creates_tunnel(self):
        repo = base_repo()
        make_admin(repo, ADMIN, CHAT_B)
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_cb_ctx(repo, bot, user_id=ADMIN, chat_id=CHAT_B)
        await feature.on_accept(ctx, from_chat=CHAT_A, to_chat=CHAT_B, by=USER)
        assert len(repo.db.chat_tunnels) == 1
        t = repo.db.chat_tunnels[0]
        assert t.id == 1
        assert t.involves(CHAT_A) and t.involves(CHAT_B)
        ctx.callback_query.edit_message_text.assert_awaited()

    async def test_accept_duplicate_rejected(self):
        repo = base_repo()
        make_admin(repo, ADMIN, CHAT_B)
        repo.db.chat_tunnels.append(
            ChatTunnel(id=5, chat_a=CHAT_A, chat_b=CHAT_B, chat_a_name="А", chat_b_name="Б", created_by=USER)
        )
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_cb_ctx(repo, bot, user_id=ADMIN, chat_id=CHAT_B)
        await feature.on_accept(ctx, from_chat=CHAT_A, to_chat=CHAT_B, by=USER)
        assert len(repo.db.chat_tunnels) == 1

    async def test_decline_requires_admin(self):
        repo = base_repo()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_cb_ctx(repo, bot, user_id=USER, chat_id=CHAT_B)
        await feature.on_decline(ctx, from_chat=CHAT_A, to_chat=CHAT_B, by=USER)
        ctx.callback_query.answer.assert_awaited()
        ctx.callback_query.edit_message_text.assert_not_awaited()


class TestSend:
    def _repo_with_tunnel(self):
        repo = base_repo()
        repo.db.chat_tunnels.append(
            ChatTunnel(id=1, chat_a=CHAT_A, chat_b=CHAT_B, chat_a_name="Чат А", chat_b_name="Чат Б", created_by=USER)
        )
        return repo

    async def test_send_forwards_and_records(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="1 привет", repo=repo, bot=bot, user_id=USER, chat_id=CHAT_A)
        result = await feature.chat(ctx)
        assert result is True
        recorded = [m for m in repo.db.tunnel_messages if m.tunnel_id == 1]
        assert len(recorded) == 1
        assert recorded[0].src_chat == CHAT_A
        assert recorded[0].dst_chat == CHAT_B

    async def test_send_unknown_tunnel(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="99 привет", repo=repo, bot=bot, user_id=USER, chat_id=CHAT_A)
        await feature.chat(ctx)
        assert "не найден" in reply_of(ctx)

    async def test_send_from_unrelated_chat(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="1 привет", repo=repo, bot=bot, user_id=USER, chat_id=-100999)
        await feature.chat(ctx)
        assert "не найден" in reply_of(ctx)
        assert repo.db.tunnel_messages == []


class TestSendReply:
    """/tunnel <id> как reply на любое сообщение → переслать его в туннель."""

    def _repo_with_tunnel(self):
        repo = base_repo()
        repo.db.chat_tunnels.append(
            ChatTunnel(id=1, chat_a=CHAT_A, chat_b=CHAT_B, chat_a_name="Чат А", chat_b_name="Чат Б", created_by=USER)
        )
        return repo

    async def test_reply_text_forwarded(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="1", repo=repo, bot=bot, user_id=USER, chat_id=CHAT_A)
        ctx.message.reply_to_message = MagicMock(message_id=42, text="исходный текст")
        result = await feature.chat(ctx)
        assert result is True
        recorded = [m for m in repo.db.tunnel_messages if m.tunnel_id == 1]
        assert len(recorded) == 1
        assert recorded[0].src_chat == CHAT_A
        assert recorded[0].dst_chat == CHAT_B
        # Back-reply из другого чата должен целиться в исходное сообщение.
        assert recorded[0].src_msg_id == 42

    async def test_reply_media_forwarded(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="1", repo=repo, bot=bot, user_id=USER, chat_id=CHAT_A)
        ctx.message.reply_to_message = MagicMock(message_id=42, text=None)  # медиа
        result = await feature.chat(ctx)
        assert result is True
        recorded = [m for m in repo.db.tunnel_messages if m.tunnel_id == 1]
        assert len(recorded) == 1
        assert recorded[0].src_msg_id == 42

    async def test_without_reply_hints(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="1", repo=repo, bot=bot, user_id=USER, chat_id=CHAT_A)
        ctx.message.reply_to_message = None
        result = await feature.chat(ctx)
        assert result is True
        assert repo.db.tunnel_messages == []
        assert "ответьте" in reply_of(ctx).lower() or "reply" in reply_of(ctx).lower()

    async def test_reply_unknown_tunnel(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="99", repo=repo, bot=bot, user_id=USER, chat_id=CHAT_A)
        ctx.message.reply_to_message = MagicMock(message_id=42, text="x")
        await feature.chat(ctx)
        assert "не найден" in reply_of(ctx)
        assert repo.db.tunnel_messages == []

    async def test_reply_to_album_forwards_all_parts(self):
        """Bug 2: реплай-командой на альбом (несколько фото) пересылает весь
        альбом одним copy_messages, а не одну картинку."""
        repo = self._repo_with_tunnel()
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=200))
        bot.copy_messages = AsyncMock(return_value=[
            MagicMock(message_id=201),
            MagicMock(message_id=202),
            MagicMock(message_id=203),
        ])
        bot.set_message_reaction = AsyncMock()
        feature = make_feature(repo, bot)

        client = MagicMock()
        # Соседние id, из них part альбома — те, у кого grouped_id совпадает.
        client.get_messages = AsyncMock(return_value=[
            MagicMock(id=41, grouped_id=555),
            MagicMock(id=42, grouped_id=555),
            MagicMock(id=43, grouped_id=555),
            MagicMock(id=44, grouped_id=999),  # сосед из другой группы — отсев
        ])

        ctx = make_context("tunnel", args="1", repo=repo, bot=bot, user_id=USER, chat_id=CHAT_A)
        ctx.client = client
        ctx.message.reply_to_message = MagicMock(message_id=42, media_group_id="555")

        result = await feature.chat(ctx)
        assert result is True
        bot.copy_messages.assert_awaited_once()
        assert bot.copy_messages.call_args.kwargs["message_ids"] == [41, 42, 43]
        # На каждую часть альбома записан маппинг — реплай на любую уйдёт назад.
        recorded = [m for m in repo.db.tunnel_messages if m.tunnel_id == 1]
        assert len(recorded) == 3
        assert {m.dst_msg_id for m in recorded} == {201, 202, 203}


class TestCaptionSend:
    """Медиа с командой в подписи: «/tunnel <id> [текст]» на фото/видео."""

    def _repo_with_tunnel(self):
        repo = base_repo()
        repo.db.chat_tunnels.append(
            ChatTunnel(id=1, chat_a=CHAT_A, chat_b=CHAT_B, chat_a_name="Чат А", chat_b_name="Чат Б", created_by=USER)
        )
        return repo

    def _media_caption_ctx(self, repo, bot, caption, chat_id=CHAT_A):
        update = make_text_update("", user_id=USER, chat_id=chat_id)
        update.message.text = None  # медиа без текста
        update.message.caption = caption
        update.message.message_id = 70
        update.message.reply_to_message = None
        from steward.bot.context import ChatBotContext

        return ChatBotContext(
            repository=repo, bot=bot, client=MagicMock(), update=update,
            tg_context=MagicMock(), metrics=MagicMock(), message=update.message,
        )

    async def test_media_caption_forwarded(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = self._media_caption_ctx(repo, bot, "/tunnel 1 смотри сюда")
        result = await feature.chat(ctx)
        assert result is True
        recorded = [m for m in repo.db.tunnel_messages if m.tunnel_id == 1]
        assert len(recorded) == 1
        assert recorded[0].src_chat == CHAT_A
        assert recorded[0].dst_chat == CHAT_B
        assert recorded[0].src_msg_id == 70

    async def test_media_caption_no_text(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = self._media_caption_ctx(repo, bot, "/tunnel 1")
        result = await feature.chat(ctx)
        assert result is True
        assert len([m for m in repo.db.tunnel_messages if m.tunnel_id == 1]) == 1

    async def test_caption_unknown_tunnel(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = self._media_caption_ctx(repo, bot, "/tunnel 99 hi")
        result = await feature.chat(ctx)
        assert result is True
        assert "не найден" in reply_of(ctx)
        assert repo.db.tunnel_messages == []

    async def test_non_tunnel_caption_ignored(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = self._media_caption_ctx(repo, bot, "просто подпись к фото")
        result = await feature.chat(ctx)
        assert result is False
        assert repo.db.tunnel_messages == []


class TestReplyForwarding:
    async def test_reply_forwarded_back(self):
        repo = base_repo()
        repo.db.chat_tunnels.append(
            ChatTunnel(id=1, chat_a=CHAT_A, chat_b=CHAT_B, chat_a_name="Чат А", chat_b_name="Чат Б", created_by=USER)
        )
        # A message that originated in CHAT_A, forwarded into CHAT_B as msg 20.
        repo.db.tunnel_messages.append(
            TunnelMessage(tunnel_id=1, src_chat=CHAT_A, src_msg_id=10, dst_chat=CHAT_B, dst_msg_id=20, sender_id=USER)
        )
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)

        update = make_text_update("ответ из Б", user_id=ADMIN, chat_id=CHAT_B)
        update.message.reply_to_message = MagicMock(message_id=20)
        from steward.bot.context import ChatBotContext

        ctx = ChatBotContext(
            repository=repo,
            bot=bot,
            client=MagicMock(),
            update=update,
            tg_context=MagicMock(),
            metrics=MagicMock(),
            message=update.message,
        )
        result = await feature.chat(ctx)
        assert result is True
        # New mapping recorded for the reply (so the chain keeps working).
        back = [m for m in repo.db.tunnel_messages if m.src_chat == CHAT_B]
        assert len(back) == 1
        assert back[0].dst_chat == CHAT_A

    async def test_media_reply_forwarded(self):
        repo = base_repo()
        repo.db.chat_tunnels.append(
            ChatTunnel(id=1, chat_a=CHAT_A, chat_b=CHAT_B, chat_a_name="Чат А", chat_b_name="Чат Б", created_by=USER)
        )
        repo.db.tunnel_messages.append(
            TunnelMessage(tunnel_id=1, src_chat=CHAT_A, src_msg_id=10, dst_chat=CHAT_B, dst_msg_id=20, sender_id=USER)
        )
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)

        update = make_text_update("", user_id=ADMIN, chat_id=CHAT_B)
        update.message.text = None  # медиа без текста (стикер/фото)
        update.message.message_id = 55
        update.message.reply_to_message = MagicMock(message_id=20)
        from steward.bot.context import ChatBotContext

        ctx = ChatBotContext(
            repository=repo, bot=bot, client=MagicMock(), update=update,
            tg_context=MagicMock(), metrics=MagicMock(), message=update.message,
        )
        result = await feature.chat(ctx)
        assert result is True
        back = [m for m in repo.db.tunnel_messages if m.src_chat == CHAT_B]
        assert len(back) == 1
        assert back[0].dst_chat == CHAT_A

    async def test_reply_to_own_sent_continues_tunnel(self):
        """Bug 1: реплай на своё же отправленное в туннель сообщение продолжает
        туннель в ту же сторону — без повторной команды /tunnel <id>."""
        repo = base_repo()
        repo.db.chat_tunnels.append(
            ChatTunnel(id=1, chat_a=CHAT_A, chat_b=CHAT_B, chat_a_name="Чат А", chat_b_name="Чат Б", created_by=USER)
        )
        # USER из CHAT_A раньше отправил msg 10 → доставлено в CHAT_B как msg 20.
        repo.db.tunnel_messages.append(
            TunnelMessage(tunnel_id=1, src_chat=CHAT_A, src_msg_id=10, dst_chat=CHAT_B, dst_msg_id=20, sender_id=USER)
        )
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)

        update = make_text_update("дописка", user_id=USER, chat_id=CHAT_A)
        update.message.message_id = 30
        update.message.reply_to_message = MagicMock(message_id=10, media_group_id=None)
        from steward.bot.context import ChatBotContext

        ctx = ChatBotContext(
            repository=repo, bot=bot, client=MagicMock(), update=update,
            tg_context=MagicMock(), metrics=MagicMock(), message=update.message,
        )
        result = await feature.chat(ctx)
        assert result is True
        # Новая пара: из A в B (то же направление, что и исходное сообщение).
        extra = [m for m in repo.db.tunnel_messages if m.src_msg_id == 30]
        assert len(extra) == 1
        assert extra[0].src_chat == CHAT_A and extra[0].dst_chat == CHAT_B

    async def test_non_reply_ignored(self):
        repo = base_repo()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        update = make_text_update("просто текст", user_id=USER, chat_id=CHAT_B)
        update.message.reply_to_message = None
        from steward.bot.context import ChatBotContext

        ctx = ChatBotContext(
            repository=repo, bot=bot, client=MagicMock(), update=update,
            tg_context=MagicMock(), metrics=MagicMock(), message=update.message,
        )
        result = await feature.chat(ctx)
        assert result is False


class TestNames:
    async def test_private_chat_name_uses_username(self):
        repo = base_repo()
        # ЛС: chat_id == user_id; показываем @username (не имя, не «Unknown»).
        repo.db.users.append(User(123, "vasya", [123], first_name="Вася"))
        feature = make_feature(repo)
        assert feature._chat_name(123) == "@vasya"

    async def test_user_without_username_falls_back_to_name(self):
        repo = base_repo()
        repo.db.users.append(User(124, None, [124], first_name="Петя"))
        feature = make_feature(repo)
        assert feature._chat_name(124) == "Петя"

    async def test_unknown_chat_name_not_leaked(self):
        repo = base_repo()
        repo.db.chats.append(Chat(id=-100333, name="Unknown"))
        feature = make_feature(repo)
        assert "Unknown" not in feature._chat_name(-100333)


class TestRemove:
    def _repo_with_tunnel(self):
        repo = base_repo()
        repo.db.chat_tunnels.append(
            ChatTunnel(id=1, chat_a=CHAT_A, chat_b=CHAT_B, chat_a_name="Чат А", chat_b_name="Чат Б", created_by=USER)
        )
        repo.db.tunnel_messages.append(
            TunnelMessage(tunnel_id=1, src_chat=CHAT_A, src_msg_id=10, dst_chat=CHAT_B, dst_msg_id=20, sender_id=USER)
        )
        return repo

    async def test_remove_requires_admin(self):
        repo = self._repo_with_tunnel()
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="rm 1", repo=repo, bot=bot, user_id=USER, chat_id=CHAT_A)
        await feature.chat(ctx)
        assert len(repo.db.chat_tunnels) == 1
        assert "чатадмин" in reply_of(ctx).lower()

    async def test_admin_removes_tunnel_and_messages(self):
        repo = self._repo_with_tunnel()
        make_admin(repo, ADMIN, CHAT_A)
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="rm 1", repo=repo, bot=bot, user_id=ADMIN, chat_id=CHAT_A)
        result = await feature.chat(ctx)
        assert result is True
        assert repo.db.chat_tunnels == []
        assert repo.db.tunnel_messages == []

    async def test_remove_other_chat_tunnel_denied(self):
        repo = self._repo_with_tunnel()
        make_admin(repo, ADMIN, -100999)
        bot, _ = await make_bot()
        feature = make_feature(repo, bot)
        ctx = make_context("tunnel", args="rm 1", repo=repo, bot=bot, user_id=ADMIN, chat_id=-100999)
        await feature.chat(ctx)
        assert len(repo.db.chat_tunnels) == 1
        assert "не найден" in reply_of(ctx)

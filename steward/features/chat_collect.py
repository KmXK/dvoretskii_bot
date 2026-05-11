import asyncio
import logging

from steward.data.models.chat import Chat
from steward.data.models.user import User
from steward.framework import Feature, FeatureContext, collection, on_init, on_message
from steward.helpers.avatars import has_cached_avatar, try_fetch_from_bot

logger = logging.getLogger(__name__)


class ChatCollectFeature(Feature):
    chats = collection("chats")
    users = collection("users")

    _chat_ids: set[int]
    _users_by_id: dict[int, User]
    _avatar_attempted: set[int]

    @on_init
    def _populate_cache(self):
        self._avatar_attempted = set()
        self._update_cache()

    def _update_cache(self):
        self._chat_ids = set(c.id for c in self.chats)
        self._users_by_id = {u.id: u for u in self.users}

    def _kick_avatar_fetch(self, user_id: int) -> None:
        if user_id in self._avatar_attempted:
            return
        self._avatar_attempted.add(user_id)
        if has_cached_avatar(user_id):
            return

        async def _do():
            try:
                await try_fetch_from_bot(self.bot, user_id)
            except Exception:
                logger.exception("avatar background fetch for %s failed", user_id)

        asyncio.create_task(_do())

    @on_message
    async def collect(self, ctx: FeatureContext) -> bool:
        if ctx.message is None:
            return False
        message = ctx.message
        chat_id = message.chat.id
        changed = False

        if chat_id not in self._chat_ids:
            existing_chat = next((c for c in self.chats if c.id == chat_id), None)
            if existing_chat is None or existing_chat.name == "Unknown":
                if existing_chat is None:
                    self.chats.add(
                        Chat(
                            chat_id,
                            message.chat.title or f"@{message.chat.username}",
                        )
                    )
                else:
                    existing_chat.name = (
                        message.chat.title or f"@{message.chat.username}"
                    )
                changed = True

        from_user = message.from_user
        if from_user is not None:
            user_id = from_user.id
            username = from_user.username
            first_name = from_user.first_name
            existing_user = self._users_by_id.get(user_id)
            if existing_user is None:
                self.users.add(User(user_id, username, [chat_id], first_name=first_name))
                changed = True
            else:
                if existing_user.username != username:
                    existing_user.username = username
                    changed = True
                if first_name and existing_user.first_name != first_name:
                    existing_user.first_name = first_name
                    changed = True
                if not hasattr(existing_user, "chat_ids"):
                    existing_user.chat_ids = []
                if chat_id not in existing_user.chat_ids:
                    existing_user.chat_ids.append(chat_id)
                    changed = True

        if changed:
            await self.users.save()
            self._update_cache()
        if from_user is not None:
            self._kick_avatar_fetch(from_user.id)
        return False

from steward.data.models.chat import Chat
from steward.data.models.user import User
from steward.handlers.handler import Handler


class ChatCollectHandler(Handler):
    def init(self):
        self._update_cache()

    async def chat(self, context):
        changed = False

        chat_id = context.message.chat.id
        if chat_id not in self.chats_ids:
            if not any(chat.id == chat_id for chat in self.repository.db.chats) or self.repository.db.chats.get(chat_id).name == "Unknown":
                self.repository.db.chats.append(
                    Chat(
                        chat_id,
                        context.message.chat.title or f"@{context.message.chat.username}",
                    )
                )
                changed = True

        from_user = context.message.from_user
        if from_user:
            user_id = from_user.id
            username = from_user.username
            existing = self.users_by_id.get(user_id)
            if existing is None:
                self.repository.db.users.append(User(user_id, username, [chat_id]))
                changed = True
            else:
                if existing.username != username:
                    existing.username = username
                    changed = True
                if not hasattr(existing, 'chat_ids'):
                    existing.chat_ids = []
                if chat_id not in existing.chat_ids:
                    existing.chat_ids.append(chat_id)
                    changed = True

        if changed:
            await self.repository.save()
            self._update_cache()

        return False

    def _update_cache(self):
        self.chats_ids = set(chat.id for chat in self.repository.db.chats)
        self.users_by_id = {user.id: user for user in self.repository.db.users}

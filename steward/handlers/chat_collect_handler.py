from telegram import Update

from steward.data.models.chat import Chat
from steward.data.repository import Repository
from steward.handlers.handler import Handler


class ChatCollectHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository
        self._update_chats()

    async def chat(self, update: Update, context):
        assert update.message and update.message.chat
        if update.message.chat.id not in self.chats_ids:
            self.repository.db.chats.append(
                Chat(
                    update.message.chat.id,
                    update.message.chat.title or "Unknown",
                )
            )
            await self.repository.save()
            self._update_chats()

        return False

    def _update_chats(self):
        self.chats_ids = set((chat.id for chat in self.repository.db.chats))

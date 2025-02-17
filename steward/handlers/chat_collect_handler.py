from steward.data.models.chat import Chat
from steward.handlers.handler import Handler


class ChatCollectHandler(Handler):
    def init(self):
        self._update_chats()

    async def chat(self, context):
        if context.message.chat.id not in self.chats_ids:
            self.repository.db.chats.append(
                Chat(
                    context.message.chat.id,
                    context.message.chat.title or "Unknown",
                )
            )
            await self.repository.save()
            self._update_chats()

        return False

    def _update_chats(self):
        self.chats_ids = set((chat.id for chat in self.repository.db.chats))

from steward.data.models.chat import Chat
from steward.handlers.handler import Handler


class ChatCollectHandler(Handler):
    def init(self):
        self._update_chats()

    async def chat(self, context):
        chat_id = context.message.chat.id
        if chat_id not in self.chats_ids:
            if not any(chat.id == chat_id for chat in self.repository.db.chats):
                self.repository.db.chats.append(
                    Chat(
                        chat_id,
                        context.message.chat.title or "Unknown",
                    )
                )
                await self.repository.save()
                self._update_chats()

        return False

    def _update_chats(self):
        self.chats_ids = set((chat.id for chat in self.repository.db.chats))

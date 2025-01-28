from telegram import Update


class Step:
    async def chat(self, update: Update, session_context: dict) -> bool:
        return True

    async def callback(self, update: Update, session_context: dict) -> bool:
        return True

    def stop(self):
        pass
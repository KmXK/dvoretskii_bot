from steward.session.context import CallbackStepContext, ChatStepContext


class Step:
    async def chat(self, context: ChatStepContext) -> bool:
        return True

    async def callback(self, context: CallbackStepContext) -> bool:
        return True

    def stop(self):
        pass

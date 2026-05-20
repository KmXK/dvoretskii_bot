from steward.session.context import CallbackStepContext, ChatStepContext, ReactionStepContext


class Step:
    async def chat(self, context: ChatStepContext) -> bool:
        return True

    async def callback(self, context: CallbackStepContext) -> bool:
        return True

    async def reaction(self, context: ReactionStepContext) -> bool:
        return False

    def stop(self):
        pass

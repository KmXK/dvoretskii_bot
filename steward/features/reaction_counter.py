from steward.framework import Feature, FeatureContext, on_reaction
from steward.helpers.reactions import get_reactions_info


class ReactionCounterFeature(Feature):
    @on_reaction
    async def count(self, ctx: FeatureContext) -> bool:
        await get_reactions_info(ctx)
        return False

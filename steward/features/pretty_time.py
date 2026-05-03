import logging

from steward.delayed_action.pretty_time import PrettyTimeDelayedAction
from steward.framework import Feature, FeatureContext, collection, subcommand

logger = logging.getLogger(__name__)


class PrettyTimeFeature(Feature):
    command = "pretty_time"
    only_admin = True
    description = "Красивое время в чате"

    delayed_actions = collection("delayed_actions")

    @subcommand("delete", description="Удалить вывод красивого времени")
    async def delete(self, ctx: FeatureContext):
        chat_id = ctx.chat_id
        action = self.delayed_actions.find_one(
            lambda x: isinstance(x, PrettyTimeDelayedAction) and x.chat_id == chat_id
        )
        if action is not None:
            self.delayed_actions.remove(action)
            await self.delayed_actions.save()

    @subcommand("", description="Включить вывод")
    async def add(self, ctx: FeatureContext):
        chat_id = ctx.chat_id
        action = self.delayed_actions.find_one(
            lambda x: isinstance(x, PrettyTimeDelayedAction) and x.chat_id == chat_id
        )
        if action is None:
            self.delayed_actions.add(PrettyTimeDelayedAction(chat_id=chat_id))
            await self.delayed_actions.save()

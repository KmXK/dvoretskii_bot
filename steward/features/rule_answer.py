import logging
import random
import re

from steward.data.models.rule import Rule
from steward.framework import Feature, FeatureContext, collection, on_message

logger = logging.getLogger(__name__)


class RuleAnswerFeature(Feature):
    rules = collection("rules")

    @on_message
    async def answer(self, ctx: FeatureContext) -> bool:
        if ctx.message is None or not isinstance(ctx.message.text, str):
            return False
        rules_list = list(self.rules)

        def matches(rule: Rule) -> bool:
            if not re.search(
                rule.pattern.regex,
                ctx.message.text,
                re.IGNORECASE if rule.pattern.ignore_case_flag == 1 else 0,
            ):
                return False
            return any(
                ctx.user_id in x.from_users or 0 in x.from_users for x in rules_list
            )

        available = [r for r in rules_list if matches(r)]
        if not available:
            return False
        rule = random.choice(available)
        probability_sum = sum(r.probability for r in rule.responses)
        probability_choice = random.randint(0, 999)
        if probability_choice >= probability_sum:
            return False

        lower_bound = 0
        idx = 0
        while idx < len(rule.responses) and lower_bound + rule.responses[idx].probability <= probability_choice:
            lower_bound += rule.responses[idx].probability
            idx += 1
        if idx >= len(rule.responses):
            return False
        response = rule.responses[idx]
        if response.text is not None:
            await ctx.message.reply_text(response.text)
        else:
            await ctx.message.reply_copy(response.from_chat_id, response.message_id)
        return True

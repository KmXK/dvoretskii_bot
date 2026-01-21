import logging
import random
import re

from steward.data.models.rule import Rule
from steward.handlers.handler import Handler


class RuleAnswerHandler(Handler):
    async def chat(self, context):
        rules = self.repository.db.rules

        def does_rule_match(rule: Rule):
            return (
                isinstance(context.message.text, str)
                and re.search(
                    rule.pattern.regex,
                    context.message.text,
                    re.IGNORECASE if rule.pattern.ignore_case_flag == 1 else 0,
                )
                and any(
                    context.message.from_user.id in x.from_users or 0 in x.from_users
                    for x in rules
                )
            )

        available_rules = [rule for rule in rules if does_rule_match(rule)]

        if len(available_rules) == 0:
            return

        rule = random.choice(available_rules)
        probability_sum = sum(response.probability for response in rule.responses)
        logging.info(f"sum of promille is {probability_sum}")

        probability_choice = random.randint(0, 999)
        logging.info(f"probability choice is {probability_choice}")

        if probability_choice >= probability_sum:
            logging.info("bot will not respond (probability_choice >= probability_sum)")
            return

        lower_bound = 0
        response_index = 0

        while (
            response_index < len(rule.responses)
            and lower_bound + rule.responses[response_index].probability
            <= probability_choice
        ):
            lower_bound += rule.responses[response_index].probability
            response_index += 1

        if response_index >= len(rule.responses):
            logging.warning("response_index out of bounds, not responding")
            return

        logging.info(f"selected {response_index} response")

        response = rule.responses[response_index]

        if response.text is not None:
            await context.message.reply_text(response.text)
        else:
            await context.message.reply_copy(response.from_chat_id, response.message_id)

        return True

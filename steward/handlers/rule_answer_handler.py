import logging
import random
import re

from steward.data.models.rule import Rule
from steward.data.repository import Repository
from steward.handlers.handler import Handler


class RuleAnswerHandler(Handler):
    def __init__(self, repository: Repository):
        self.repository = repository

    async def chat(self, update, context):
        rules = self.repository.db.rules

        message = update.message

        def does_rule_match(rule: Rule):
            return (
                isinstance(message.text, str)
                and re.match(
                    rule.pattern.regex,
                    message.text,
                    re.IGNORECASE if rule.pattern.ignore_case_flag == 1 else 0,
                )
                and any(
                    filter[Rule](
                        lambda rule: message.from_user.id in rule.from_users
                        or 0 in rule.from_users,
                        rules,
                    )
                )
            )

        available_rules = [rule for rule in rules if does_rule_match(rule)]

        if len(available_rules) == 0:
            return

        rule = random.choice(available_rules)
        probability_max = sum(rule.probability for rule in rule.responses)
        logging.info(f"sum is {probability_max}")

        probability_choice = random.randint(0, probability_max - 1)
        logging.info(f"probability choice is {probability_choice}")
        lower_bound = 0
        response_index = 0

        # while upper_bound is less than probability_max
        while (
            lower_bound + rule.responses[response_index].probability - 1
            < probability_choice
        ):
            lower_bound += rule.responses[response_index].probability
            response_index += 1

        logging.info(f"selected {response_index} response")

        response = rule.responses[response_index]

        if response.text is not None:
            await message.reply_text(response.text)
        else:
            await message.reply_copy(response.from_chat_id, response.message_id)

        return True

import logging
import random
import re

from telegram import ReactionTypeEmoji

from steward.data.models.rule import Rule
from steward.framework import Feature, FeatureContext, collection, on_message

logger = logging.getLogger(__name__)


class RuleAnswerFeature(Feature):
    rules = collection("rules")

    _AI_TRIGGERS = ["дворецкий", "уважаемый"]
    _AI_MEDIA_ATTRS = ("video", "video_note", "voice", "audio", "photo", "sticker", "animation", "document")

    def _addressed_to_ai(self, ctx: FeatureContext) -> bool:
        text = ctx.message.text or ""
        text_lower = text.lower()
        bot_username = ctx.bot.username
        if bot_username and text_lower.startswith(f"@{bot_username.lower()}"):
            return True
        if any(text_lower.startswith(t) for t in self._AI_TRIGGERS):
            return True
        reply = ctx.message.reply_to_message
        if reply:
            from_bot = reply.from_user and reply.from_user.id == ctx.bot.id
            is_media = any(getattr(reply, a, None) for a in self._AI_MEDIA_ATTRS)
            if from_bot and not is_media:
                return True
        return False

    @on_message
    async def answer(self, ctx: FeatureContext) -> bool:
        if ctx.message is None or not isinstance(ctx.message.text, str):
            return False
        if self._addressed_to_ai(ctx):
            return False
        rules_list = list(self.rules)

        def matches(rule: Rule) -> bool:
            # Правило срабатывает только в чатах из своего скоупа.
            if ctx.chat_id not in rule.chats:
                return False
            if not re.search(
                rule.pattern.regex,
                ctx.message.text,
                re.IGNORECASE if rule.pattern.ignore_case_flag == 1 else 0,
            ):
                return False
            # from_users пуст => не от кого; {0} => от всех.
            return ctx.user_id in rule.from_users or 0 in rule.from_users

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
        if response.reaction_emoji is not None:
            await ctx.message.set_reaction([ReactionTypeEmoji(emoji=response.reaction_emoji)])
        elif response.text is not None:
            await ctx.message.reply_text(response.text)
        else:
            await ctx.message.reply_copy(response.from_chat_id, response.message_id)
        return True

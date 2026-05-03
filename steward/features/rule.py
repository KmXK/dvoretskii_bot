import logging
import re
import textwrap

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.data.models.rule import Response, Rule, RulePattern
from steward.framework import (
    Feature,
    FeatureContext,
    ask,
    choice,
    collection,
    step,
    subcommand,
    wizard,
)
from steward.helpers.tg_update_helpers import get_message
from steward.helpers.validation import check, try_get, validate_message_text
from steward.session.step import Step

logger = logging.getLogger(__name__)


class _CollectResponsesStep(Step):
    def __init__(self):
        self.is_waiting = False

    async def chat(self, context):
        response = Response(
            context.message.chat_id, context.message.message_id, 100
        )
        await context.message.chat.copy_message(
            context.message.chat_id, context.message.message_id
        )
        context.session_context["responses"].append(response)
        return False

    async def callback(self, context):
        if not self.is_waiting:
            context.session_context["responses"] = []
            await context.bot.send_message(
                context.callback_query.message.chat.id,
                "Ответы на сообщение (пишите отдельными сообщениями, можно пересылать, можно отправлять стикеры, картинки, видео и аудио):",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "Ответы закончились",
                            callback_data="rule_handler|end_responses",
                        ),
                    ],
                ]),
            )
            self.is_waiting = True
            return False

        if len(context.session_context["responses"]) == 0:
            await context.callback_query.message.chat.send_message(
                "Количество ответов не может быть нулевым"
            )
            return False
        if context.callback_query.data == "rule_handler|end_responses":
            return True
        return False

    def stop(self):
        self.is_waiting = False


class _CheckRegexpStep(Step):
    def __init__(self):
        self.is_first = True

    async def chat(self, context):
        if self.is_first:
            await context.message.reply_text(
                'Проверка шаблона, отправляйте сообщения, а после нажмите кнопку "Закончить" в конце',
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "Закончить",
                            callback_data="rule_handler|end_check_regexp",
                        ),
                    ],
                ]),
            )
            self.is_first = False
            return False
        if not context.message.text:
            await context.message.reply_text("Пустое сообщение")
            return False
        result = re.search(context.session_context["pattern"], context.message.text)
        await context.message.reply_text("Подходит" if result else "Не подходит")
        return False

    async def callback(self, context):
        if context.callback_query.data == "rule_handler|end_check_regexp":
            return True
        return False

    def stop(self):
        self.is_first = True


class RuleFeature(Feature):
    command = "rule"
    only_admin = True
    description = "Управление правилами-ответами"

    rules = collection("rules")

    @subcommand("", description="Список правил")
    async def list_(self, ctx: FeatureContext):
        if not list(self.rules):
            await ctx.reply("Правил нет")
            return
        lines = ["Правила:", ""]
        for rule in self.rules:
            lines.append(_render_rule(rule))
        await ctx.reply("\n".join(lines))

    @subcommand("add", description="Добавить правило (сессия)")
    async def add(self, ctx: FeatureContext):
        await self.start_wizard("rule:add", ctx)

    @subcommand("remove <ids:rest>", description="Удалить правила")
    async def remove(self, ctx: FeatureContext, ids: str):
        for rule_id_str in ids.split():
            try:
                rule_id = int(rule_id_str)
            except ValueError:
                await ctx.reply(f"Ошибка. Id правила должно быть целым числом: {rule_id_str}")
                continue
            rule = self.rules.find_by(id=rule_id)
            if rule is None:
                await ctx.reply(f"Ошибка. Правила с id={rule_id} не существует")
            else:
                self.rules.remove(rule)
                await self.rules.save()
                await ctx.reply(f"Правило {rule_id} удалено")

    @subcommand("<rule_id:int>", description="Просмотр правила")
    async def view(self, ctx: FeatureContext, rule_id: int):
        rule = self.rules.find_by(id=rule_id)
        if rule is None:
            await ctx.reply("Правила с таким id не существует")
            return
        await ctx.reply(_render_rule(rule))

    @wizard(
        "rule:add",
        ask(
            "from_users",
            "От кого? (id пользователей через пробел)",
            validator=validate_message_text([
                try_get(lambda t: t.split(" ")),
                try_get(
                    lambda ids: [int(i) for i in ids],
                    "Id пользователей должны быть целыми числами",
                ),
            ]),
        ),
        ask(
            "pattern",
            "Шаблон правила (регулярное выражение)",
            validator=validate_message_text([
                check(
                    lambda pattern: re.compile(pattern) is not None,
                    "Некорректное регулярное выражение",
                ),
            ]),
        ),
        step("regexp_check", _CheckRegexpStep()),
        step("responses_collected", _CollectResponsesStep()),
        ask(
            "probabilities",
            lambda c: (
                f"Напишите промилле для ответов ({len(c['responses'])})(через пробел)."
                " Например 100 = 10%, 200 = 20%. Сумма не должна превышать 1000."
            ),
            validator=validate_message_text([
                try_get(lambda t: t.split(" ")),
                try_get(
                    lambda ids: [int(i) for i in ids],
                    "Промилле должны быть целыми числами",
                ),
                check(
                    lambda ids, c: len(ids) == len(c["responses"]),
                    "Количество промилле не совпадает с количеством ответов",
                ),
                check(
                    lambda ids: all(0 <= i <= 1000 for i in ids),
                    "Каждое значение промилле должно быть от 0 до 1000",
                ),
                check(
                    lambda ids: sum(ids) <= 1000,
                    "Сумма промилле не должна превышать 1000",
                ),
            ]),
        ),
        choice(
            "ignore_case_flag",
            "Игнорировать регистр?",
            [("Да", 1), ("Нет", 0)],
        ),
    )
    async def on_done(self, ctx: FeatureContext, **state):
        responses = state["responses"]
        for index, response in enumerate(responses):
            response.probability = state["probabilities"][index]
        new_rule = self.rules.add(
            Rule(
                id=0,
                from_users=state["from_users"],
                pattern=RulePattern(
                    regex=state["pattern"],
                    ignore_case_flag=state["ignore_case_flag"],
                ),
                responses=responses,
                tags=[],
            )
        )
        await self.rules.save()
        await get_message(ctx.update).chat.send_message(
            f"Правило добавлено c id {new_rule.id}"
        )


def _render_rule(rule: Rule) -> str:
    return textwrap.dedent(f"""\
        id: {rule.id}
        От: {", ".join([str(i) for i in rule.from_users])}
        Текст: {rule.pattern.regex}
        Количество ответов: {len(rule.responses)}
        Игнорировать регистр: {rule.pattern.ignore_case_flag}
    """)

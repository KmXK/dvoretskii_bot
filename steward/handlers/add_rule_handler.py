import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.data.models.rule import Response, Rule, RulePattern
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.tg_update_helpers import get_message
from steward.helpers.validation import check, try_get, validate_message_text
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step
from steward.session.steps.keyboard_step import KeyboardStep
from steward.session.steps.question_step import QuestionStep


class CollectResponsesStep(Step):
    def __init__(self, name):
        self.name = name
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            context.session_context[self.name] = []
            await context.message.reply_text(
                "Ответы на сообщение (пишите отдельными сообщениями, можно пересылать, можно отправлять стикеры, картинки, видео и аудио):",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "Ответы закончились",
                            callback_data="add_rule_handler|end_responses",
                        ),
                    ],
                ]),
            )
            self.is_waiting = True
            return False  # to stay on this handler in session

        response = Response(context.message.chat_id, context.message.message_id, 100)
        await context.message.chat.copy_message(
            context.message.chat_id, context.message.message_id
        )

        context.session_context[self.name].append(response)
        return False

    async def callback(self, context):
        if len(context.session_context[self.name]) == 0:
            await context.callback_query.message.chat.send_message(
                "Количество ответов не может быть нулевым"
            )
            return False
        logging.info(context.update)
        if context.callback_query.data == "add_rule_handler|end_responses":  # type: ignore
            return True
        return False


class CheckRegexpStep(Step):
    def __init__(self):
        self.is_first = True

    async def chat(self, context):
        if not context.message.text:
            await context.message.reply_text("Пустое сообщение")
            return False

        result = re.search(context.session_context["pattern"], context.message.text)
        await context.message.reply_text("Подходит" if result else "Не подходит")

        return False

    async def callback(self, context):
        if self.is_first:
            await context.bot.send_message(
                context.callback_query.message.chat.id,
                'Проверка шаблона, отправляйте сообщения, а после нажмите кнопку "Закончить" в конце',
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "Закончить",
                            callback_data="add_rule_handler|end_check_regexp",
                        ),
                    ],
                ]),
            )
            self.is_first = False
            return False  # to stay on this handler in session

        if context.callback_query.data == "add_rule_handler|end_check_regexp":
            return True
        return False


class AddRuleHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__([
            QuestionStep(
                "from_users",
                "От кого? (id пользователей через пробел)",
                filter_answer=validate_message_text([
                    try_get(lambda t: t.split(" ")),
                    try_get(
                        lambda ids: [int(id) for id in ids],
                        "Id пользователей должны быть целыми числами",
                    ),
                ]),
            ),
            QuestionStep(
                "pattern",
                "Шаблон правила (регулярное выражение)",
                filter_answer=validate_message_text([
                    check(
                        lambda pattern: re.compile(pattern) is not None,
                        "Некорректное регулярное выражение",
                    ),
                ]),
            ),
            CheckRegexpStep(),
            CollectResponsesStep("responses"),
            QuestionStep(
                "probabilities",
                lambda ctx: f"Напишите вероятности ответов ({len(ctx['responses'])})(через пробел)",
                filter_answer=validate_message_text([
                    try_get(lambda t: t.split(" ")),
                    try_get(
                        lambda ids: [int(id) for id in ids],
                        "Вероятности должны быть целыми числами",
                    ),
                    check(
                        lambda ids, ctx: len(ids) == len(ctx["responses"]),
                        "Количество вероятностей не совпадает с количеством ответов",
                    ),
                ]),
            ),
            KeyboardStep(
                "ignore_case_flag",
                "Игнорировать регистр?",
                [
                    ("Да", "add_rule_handler|ignore", 1),
                    ("Нет", "add_rule_handler|no_ignore", 0),
                ],
            ),
        ])

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "add_rule"):
            return False

        return True

    async def on_session_finished(self, update, session_context):
        for index, response in enumerate(session_context["responses"]):
            response.probability = session_context["probabilities"][index]

        self.rule = Rule(
            from_users=session_context["from_users"],
            pattern=RulePattern(
                regex=session_context["pattern"],
                ignore_case_flag=session_context["ignore_case_flag"],
            ),
            responses=session_context["responses"],
            tags=[],
        )

        self.repository.db.rules.append(self.rule)
        await self.repository.save()

        await get_message(update).chat.send_message(
            f"Правило добавлено c id {self.rule.id}"
        )

    def help(self):
        return "/add_rule - добавить правило"

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.handler import validate_command_msg
from helpers.validation import check, try_get, validate_message_text
from models.rule import Response, Rule, RulePattern
from repository import Repository
from session.session_handler_base import SessionHandlerBase
from session.step import Step
from session.steps.keyboard_step import KeyboardStep
from session.steps.question_step import QuestionStep
from tg_update_helpers import get_message


class CollectResponsesStep(Step):
    def __init__(self, name):
        self.name = name
        self.is_waiting = False

    async def chat(self, update, session_context):
        assert update.message

        if not self.is_waiting:
            session_context[self.name] = []
            await update.message.reply_text(
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

        response = Response(update.message.chat_id, update.message.message_id, 100)
        await update.message.chat.copy_message(
            update.message.chat_id, update.message.message_id
        )

        session_context[self.name].append(response)
        return False

    async def callback(self, update, session_context):
        if len(session_context[self.name]) == 0:
            await update.callback_query.message.chat.send_message(
                "Количество ответов не может быть нулевым"
            )
            return False
        logging.info(update)
        if update.callback_query.data == "add_rule_handler|end_responses":  # type: ignore
            return True
        return False


class AddRuleHandler(SessionHandlerBase):
    def __init__(self, repository: Repository):
        self.repository = repository

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
        if not validate_command_msg(update, ["add_rule", "new_rule"]):
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
        self.repository.save()

        await get_message(update).chat.send_message(
            f"Правило добавлено c id {self.rule.id}"
        )

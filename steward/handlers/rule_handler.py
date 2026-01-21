import logging
import re
import textwrap

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import ChatBotContext
from steward.data.models.rule import Response, Rule, RulePattern
from steward.handlers.command_handler import CommandHandler, required
from steward.handlers.handler import Handler
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
        response = Response(context.message.chat_id, context.message.message_id, 100)
        await context.message.chat.copy_message(
            context.message.chat_id, context.message.message_id
        )

        context.session_context[self.name].append(response)
        return False

    async def callback(self, context):
        if not self.is_waiting:
            context.session_context[self.name] = []
            await context.bot.send_message(
                context.callback_query.message.chat.id,
                "Ответы на сообщение (пишите отдельными сообщениями, можно пересылать, можно отправлять стикеры, картинки, видео и аудио):",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Ответы закончились",
                                callback_data="rule_handler|end_responses",
                            ),
                        ],
                    ]
                ),
            )
            self.is_waiting = True
            return False  # to stay on this handler in session

        if len(context.session_context[self.name]) == 0:
            await context.callback_query.message.chat.send_message(
                "Количество ответов не может быть нулевым"
            )
            return False
        logging.info(context.update)
        if context.callback_query.data == "rule_handler|end_responses":  # type: ignore
            return True
        return False


class CheckRegexpStep(Step):
    def __init__(self):
        self.is_first = True

    async def chat(self, context):
        if self.is_first:
            await context.message.reply_text(
                'Проверка шаблона, отправляйте сообщения, а после нажмите кнопку "Закончить" в конце',
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Закончить",
                                callback_data="rule_handler|end_check_regexp",
                            ),
                        ],
                    ]
                ),
            )
            self.is_first = False
            return False  # to stay on this handler in session

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


class RuleAddHandler(SessionHandlerBase):
    def __init__(self):
        self.only_for_admin = True
        super().__init__(
            [
                QuestionStep(
                    "from_users",
                    "От кого? (id пользователей через пробел)",
                    filter_answer=validate_message_text(
                        [
                            try_get(lambda t: t.split(" ")),
                            try_get(
                                lambda ids: [int(id) for id in ids],
                                "Id пользователей должны быть целыми числами",
                            ),
                        ]
                    ),
                ),
                QuestionStep(
                    "pattern",
                    "Шаблон правила (регулярное выражение)",
                    filter_answer=validate_message_text(
                        [
                            check(
                                lambda pattern: re.compile(pattern) is not None,
                                "Некорректное регулярное выражение",
                            ),
                        ]
                    ),
                ),
                CheckRegexpStep(),
                CollectResponsesStep("responses"),
                QuestionStep(
                    "probabilities",
                    lambda ctx: f"Напишите промилле для ответов ({len(ctx['responses'])})(через пробел). Например 100 = 10%, 200 = 20%. Сумма не должна превышать 1000.",
                    filter_answer=validate_message_text(
                        [
                            try_get(lambda t: t.split(" ")),
                            try_get(
                                lambda ids: [int(id) for id in ids],
                                "Промилле должны быть целыми числами",
                            ),
                            check(
                                lambda ids, ctx: len(ids) == len(ctx["responses"]),
                                "Количество промилле не совпадает с количеством ответов",
                            ),
                            check(
                                lambda ids: all(0 <= id <= 1000 for id in ids),
                                "Каждое значение промилле должно быть от 0 до 1000",
                            ),
                            check(
                                lambda ids: sum(ids) <= 1000,
                                "Сумма промилле не должна превышать 1000",
                            ),
                        ]
                    ),
                ),
                KeyboardStep(
                    "ignore_case_flag",
                    "Игнорировать регистр?",
                    [
                        ("Да", "rule_handler|ignore", 1),
                        ("Нет", "rule_handler|no_ignore", 0),
                    ],
                ),
            ]
        )

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "rule"):
            return False

        assert update.message and update.message.text
        parts = update.message.text.split()
        if len(parts) < 2 or parts[1] != "add":
            return False

        return True

    async def on_session_finished(self, update, session_context):
        for index, response in enumerate(session_context["responses"]):
            response.probability = session_context["probabilities"][index]

        # Генерация ID как у подписок
        max_id = (
            max(rule.id for rule in self.repository.db.rules)
            if self.repository.db.rules
            else 0
        )
        new_id = max_id + 1

        self.rule = Rule(
            id=new_id,
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
        return None


class RuleRemoveHandler(Handler):
    only_for_admin = True

    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "rule"):
            return False

        assert context.message.text
        parts = context.message.text.split()
        if len(parts) < 3 or parts[1] != "remove":
            return False

        rule_ids = parts[2:]

        for rule_id_str in rule_ids:
            try:
                rule_id = int(rule_id_str)
            except ValueError:
                await context.message.reply_text(
                    f"Ошибка. Id правила должно быть целым числом: {rule_id_str}"
                )
                continue

            rule_to_remove = next(
                (x for x in self.repository.db.rules if x.id == rule_id),
                None,
            )
            if rule_to_remove is None:
                await context.message.reply_text(
                    f"Ошибка. Правила с id={rule_id} не существует"
                )
            else:
                self.repository.db.rules.remove(rule_to_remove)
                await self.repository.save()
                await context.message.reply_markdown(f"Правило {rule_id} удалено")
        return True

    def help(self):
        return None


class RuleViewHandler(Handler):
    only_for_admin = True

    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "rule"):
            return False

        assert context.message.text
        parts = context.message.text.split()
        if len(parts) < 2:
            return False

        rule_id_str = parts[1]
        if rule_id_str in ["add", "remove"]:
            return False

        try:
            rule_id = int(rule_id_str)
        except ValueError:
            await context.message.reply_text("Id правила должно быть целым числом")
            return True

        rule = next((x for x in self.repository.db.rules if x.id == rule_id), None)

        if rule is None:
            await context.message.reply_text("Правила с таким id не существует")
            return True

        strings = [
            textwrap.dedent(f"""\
                id: {rule.id}
                От: {", ".join([str(i) for i in rule.from_users])}
                Текст: {rule.pattern.regex}
                Количество ответов: {len(rule.responses)}
                Игнорировать регистр: {rule.pattern.ignore_case_flag}
        """)
        ]
        await context.message.reply_text(text="\n".join(strings))
        return True

    def help(self):
        return None


class RuleListViewHandler(Handler):
    only_for_admin = True

    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "rule"):
            return False

        assert context.message.text
        parts = context.message.text.split()
        if len(parts) > 1:
            # Если есть аргументы, это не наш случай (может быть add, remove или id)
            return False

        strings = ["Правила:", ""]
        for rule in self.repository.db.rules:
            strings.append(
                textwrap.dedent(f"""\
                    id: {rule.id}
                    От: {", ".join([str(i) for i in rule.from_users])}
                    Текст: {rule.pattern.regex}
                    Количество ответов: {len(rule.responses)}
                    Игнорировать регистр: {rule.pattern.ignore_case_flag}
            """)
            )
        await context.message.reply_text(text="\n".join(strings))
        return True

    def help(self):
        return "/rule [add|<id>|remove <id> [<id>...]] - управлять правилами"

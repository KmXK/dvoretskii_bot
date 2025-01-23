from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from models.rule import Response, Rule, RulePattern
from models.session_state import SessionState


# TODO: rewrite on separated steps via objects (not if-else)
class Session:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.state = SessionState.start
        self.rule = Rule([], RulePattern(), [], [])

    async def write_result(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        if self.state == SessionState.from_user:
            try:
                self.rule.from_users = list(map(lambda text : int(text.strip()), update.message.text.split()))
                return True
            except Exception:
                await context.bot.send_message(self.chat_id, "Ошибка, попробуйте еще раз")
                return False

        if self.state == SessionState.pattern:
            self.rule.pattern.regex = update.message.text
            return True

        if self.state == SessionState.responses:
            response = Response(self.chat_id, update.message.message_id, 100)
            await context.bot.copy_message(self.chat_id, self.chat_id, update.message.message_id)
            self.rule.responses.append(response)
            return False

        if self.state == SessionState.probabilities:
            try:
                probabilities = list(map(lambda text : int(text.strip()), update.message.text.split()))
                if len(probabilities) != len(self.rule.responses):
                    await context.bot.send_message(self.chat_id, "Количество вероятностей не совпадает с количеством ответов")
                    return False
                for index, response in enumerate(self.rule.responses):
                    response.probability = probabilities[index]
                return True
            except:
                await context.bot.send_message(self.chat_id, "Вероятности должны быть целыми числами через пробел")

        if self.state == SessionState.tags:
            self.rule.tags = list(map(lambda text : text.strip(), update.message.text.split()))
            return True

        return False

    async def next_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.state = SessionState(self.state.value + 1)

        if self.state == SessionState.from_user:
            print(self.chat_id)
            await context.bot.send_message(self.chat_id, "От кого? (можно несколько id через пробел)")

        if self.state == SessionState.pattern:
            await context.bot.send_message(self.chat_id, "Паттерн сообщения")

        if self.state == SessionState.responses:
            keyboard = [[InlineKeyboardButton("Ответы закончились", callback_data="ResponsesEnded")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(self.chat_id, "Ответы на сообщение (пишите отдельными сообщениями, можно пересылать, можно отправлять стикеры, картинки, видео и аудио)", reply_markup=reply_markup)

        if self.state == SessionState.probabilities:
            await context.bot.send_message(self.chat_id, f"Напишите вероятности ответов ({len(self.rule.responses)})(через пробел)")

        if self.state == SessionState.tags:
            await context.bot.send_message(self.chat_id, "Теги (через пробел)")

        if self.state == SessionState.register_ignore:
            keyboard = [[InlineKeyboardButton("Да", callback_data="Ignore"), InlineKeyboardButton("Нет", callback_data="NoIgnore")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(self.chat_id, "Игнорировать регистр?", reply_markup=reply_markup)

        if self.state == SessionState.finish:
            await context.bot.send_message(self.chat_id, "Правило добавлено c id " + self.rule.id)

    async def process_callback(self,update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query.data == "ResponsesEnded":
            if len(self.rule.responses):
                await self.next_message(update, context)
                await update.callback_query.edit_message_reply_markup(None)
            else:
                await context.bot.send_message(self.chat_id, "Количество ответов не может быть нулевым")
            return

        if update.callback_query.data == "Ignore":
            self.rule.pattern.ignore_case_flag = 1
            await self.next_message(update, context)
            await update.callback_query.edit_message_text("Игнорировать регистр? (Да)")
            return

        if update.callback_query.data == "NoIgnore":
            self.rule.pattern.ignore_case_flag = 0
            await self.next_message(update, context)
            await update.callback_query.edit_message_text("Игнорировать регистр? (Нет)")
            return

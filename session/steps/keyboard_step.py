from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from helpers.typing import is_list_of
from session.step import Step

type KeyboardButton = tuple[str, str, Any]
type KeyboardLine = list[KeyboardButton]
type Keyboard = list[KeyboardLine]


class KeyboardStep(Step):
    def __init__(
        self,
        name: str,
        msg: str,
        keyboard: Keyboard | KeyboardLine,
    ):
        self.name = name
        self.msg = msg
        self.is_waiting = False

        self.mapping = {}

        self.keyboard: Keyboard = []

        if is_list_of(keyboard, list):
            self.keyboard = keyboard
        elif is_list_of(keyboard, tuple):
            self.keyboard = [keyboard]

        assert isinstance(self.keyboard[0], list)

        for line in self.keyboard:
            for button in line:
                self.mapping[button[1]] = button[2]

    async def chat(self, update, session_context):
        assert update.message
        if not self.is_waiting:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(x[0], callback_data=x[1]) for x in keyboard_line]
                for keyboard_line in self.keyboard
            ])

            await update.message.reply_text(self.msg, reply_markup=markup)

            self.is_waiting = True
            return False

        return False

    async def callback(self, update, session_context):
        assert update.callback_query
        if self.mapping.get(update.callback_query.data) is not None:
            session_context[self.name] = self.mapping[update.callback_query.data]
            return True
        return False

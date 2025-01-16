import logging
from math import ceil
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from handlers.handler import CommandHandler, Handler
from repository import Repository


PAGE_SIZE = 25


def get_keyboard_markup(max_page_count: int, current_page: int) -> InlineKeyboardMarkup:
    buttons = [
        ["<<<", 0],
        ["<", current_page - 1 if current_page > 0 else 0],
        [">", current_page + 1 if current_page < max_page_count else max_page_count],
        [">>>", max_page_count],
    ]

    keyboard = [
        InlineKeyboardButton(
            button[0],
            callback_data=(
                "logs_page|-" if button[1] == current_page else f"logs_page|{button[1]}"
            ),
        )
        for button in buttons
    ]

    reply_markup = InlineKeyboardMarkup([keyboard])
    return reply_markup


def get_page_count(all_lines: list[str]) -> int:
    return ceil(len(all_lines) / PAGE_SIZE)


def get_page_content(all_lines: list[str], page: int) -> list[str]:
    min = page * PAGE_SIZE
    max = page * PAGE_SIZE + PAGE_SIZE

    if max > len(all_lines):
        max = len(all_lines)

    return all_lines[min:max]


def get_log_page(page_number: int, page_content: list[str], page_count: int) -> str:
    return "\n".join(
        [
            f"Страница {page_number + 1}/{page_count}",
            f"``` {''.join(page_content)}```",
            f"Страница {page_number + 1}/{page_count}",
        ]
    )


@CommandHandler("logs", only_admin=True)
class LogsHandler(Handler):
    def __init__(self, log_file_path: str, repository: Repository):
        self.log_file_path = log_file_path
        self.repository = repository

    async def chat(self, update, context):
        with open(self.log_file_path, 'w+') as f:
            all_lines = f.readlines()
            page_count = get_page_count(all_lines)
            current_page = page_count - 1

            await update.message.reply_markdown(
                get_log_page(
                    current_page,
                    get_page_content(all_lines, current_page),
                    page_count,
                ),
                reply_markup=get_keyboard_markup(page_count - 1, current_page),
            )
            return True

    async def callback(self, update, context):
        data = update.callback_query.data
        if not data.startswith("logs_page") or data == "logs_page|-":
            return False

        all_lines = open(self.log_file_path).readlines()
        page_count = get_page_count(all_lines)
        current_page = int(data.split("|")[1])

        await update.callback_query.edit_message_text(
            get_log_page(
                current_page,
                get_page_content(all_lines, current_page),
                page_count,
            ),
            parse_mode="Markdown",
            reply_markup=get_keyboard_markup(page_count - 1, current_page),
        )
        await update.callback_query.answer()
        return True

    def help(self):
        return "/logs - показать логи"

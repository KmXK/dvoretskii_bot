import os
import textwrap

from handlers.handler import CommandHandler, Handler
from helpers.formats import union_lists
from helpers.pagination import (
    Paginator,
)
from repository import Repository


@CommandHandler("logs", only_admin=True)
class LogsHandler(Handler):
    def __init__(self, log_file_path: str, repository: Repository):
        self.log_file_path = log_file_path
        self.repository = repository

        self.paginator = Paginator(
            unique_keyboard_name="logs",
            list_header=None,
            page_size=25,
            page_format_func=lambda ctx: "```python\n"
            + "".join(ctx.data).replace("`", "'")
            + "```",
            data_func=lambda: union_lists([
                x if len(x) <= 100 else textwrap.wrap(x, width=70)
                for x in self._get_log_data()
            ]),
            always_show_pagination=True,
            delimiter="",
            start_from_last_page=True,
        )

    async def chat(self, update, context):
        if not os.path.exists(self.log_file_path):
            open(self.log_file_path, "w").close()

        return await self.paginator.show_list(update)

    async def callback(self, update, context):
        return await self.paginator.process_callback(update)

    def help(self):
        return "/logs - показать логи"

    def _get_log_data(self) -> list[str]:
        if not os.path.exists(self.log_file_path):
            return []
        return open(self.log_file_path, "r").readlines()

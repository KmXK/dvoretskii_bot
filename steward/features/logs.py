import os
import textwrap

from steward.framework import Feature, FeatureContext, paginated, subcommand
from steward.helpers.formats import union_lists


class LogsFeature(Feature):
    command = "logs"
    only_admin = True
    description = "Показать логи"

    def __init__(self, log_file_path: str | None = None):
        super().__init__()
        self.log_file_path = log_file_path

    def _read_log_data(self) -> list[str]:
        if not self.log_file_path or not os.path.exists(self.log_file_path):
            return []
        return open(self.log_file_path, "r").readlines()

    def _data(self) -> list[str]:
        return union_lists([
            x if len(x) <= 100 else textwrap.wrap(x, width=70)
            for x in self._read_log_data()
        ])

    @subcommand("", description="Последние строки лога")
    async def show(self, ctx: FeatureContext):
        if not self.log_file_path:
            await ctx.reply("Логи не настроены")
            return
        if not os.path.exists(self.log_file_path):
            open(self.log_file_path, "w").close()
        items = self._data()
        last_page = max(0, (len(items) - 1) // 25)
        await self.paginate(ctx, "logs", page=last_page)

    @paginated("logs", per_page=25)
    def logs_page(self, ctx: FeatureContext, metadata: str):
        items = self._data()
        render = lambda batch: (
            "```python\n"
            + "\n".join(x.rstrip("\n") for x in batch).replace("`", "'")
            + "```"
        )
        return items, render

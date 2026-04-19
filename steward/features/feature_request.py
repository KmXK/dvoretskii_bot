import datetime
import re
from enum import Enum

from steward.data.models.feature_request import (
    FeatureRequest,
    FeatureRequestChange,
    FeatureRequestStatus,
)
from steward.framework import (
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    paginated,
    subcommand,
)
from steward.helpers.formats import escape_markdown, format_lined_list


_STATUS_LABELS = {
    FeatureRequestStatus.OPEN: "Открыт",
    FeatureRequestStatus.DONE: "Завершён",
    FeatureRequestStatus.DENIED: "Отклонён",
    FeatureRequestStatus.IN_PROGRESS: "В работе",
    FeatureRequestStatus.TESTING: "На тестировании",
}

_PRIORITY_EMOJI = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🔵", 5: "⚪"}


class _Filter(Enum):
    ALL = 0
    DONE = 1
    DENIED = 2
    OPENED = 3
    IN_PROGRESS = 4
    TESTING = 5


_STATUS_FILTERS = {
    _Filter.ALL: lambda x: True,
    _Filter.DONE: lambda x: x.status == FeatureRequestStatus.DONE,
    _Filter.DENIED: lambda x: x.status == FeatureRequestStatus.DENIED,
    _Filter.OPENED: lambda x: x.status == FeatureRequestStatus.OPEN,
    _Filter.IN_PROGRESS: lambda x: x.status == FeatureRequestStatus.IN_PROGRESS,
    _Filter.TESTING: lambda x: x.status == FeatureRequestStatus.TESTING,
}


_STATUS_COMMANDS = {
    "done": (
        ["Фича-реквест уже выполнен", "Фича-реквест уже отклонён", None, None, None],
        FeatureRequestStatus.DONE,
    ),
    "deny": (
        ["Фича-реквест уже выполнен", "Фича-реквест уже отклонён", None, None, None],
        FeatureRequestStatus.DENIED,
    ),
    "reopen": (
        [None, None, "Фича-реквест и так открыт", None, None],
        FeatureRequestStatus.OPEN,
    ),
    "inprogress": (
        [None, None, None, "Фича-реквест уже в работе", None],
        FeatureRequestStatus.IN_PROGRESS,
    ),
    "testing": (
        [None, None, None, None, "Фича-реквест уже на тестировании"],
        FeatureRequestStatus.TESTING,
    ),
}


_FILTER_OPTIONS = [
    ("Все", _Filter.ALL),
    ("Завершённые", _Filter.DONE),
    ("Отклонённые", _Filter.DENIED),
    ("Открытые", _Filter.OPENED),
    ("В работе", _Filter.IN_PROGRESS),
    ("Тестирование", _Filter.TESTING),
]


class FeatureRequestFeature(Feature):
    command = "fr"
    aliases = ("featurerequest",)
    description = "Управление фича-реквестами"
    help_examples = [
        "«добавь фичу тёмная тема» → /fr тёмная тема",
        "«покажи фича-реквесты» → /fr list",
        "«отметь фичу 7 выполненной» → /fr done 7",
        "«установи приоритет 1 для фичи 3» → /fr 3 priority 1",
    ]

    feature_requests = collection("feature_requests")

    @subcommand("", description="Список открытых")
    async def list_default(self, ctx: FeatureContext):
        await self.paginate(ctx, "frs", metadata=str(_Filter.OPENED.value))

    @subcommand("list", description="Список открытых")
    async def list_alias(self, ctx: FeatureContext):
        await self.paginate(ctx, "frs", metadata=str(_Filter.OPENED.value))

    @subcommand("<fr_id:int> priority <p:int>", description="Сменить приоритет")
    async def set_priority(self, ctx: FeatureContext, fr_id: int, p: int):
        if p < 1 or p > 5:
            await ctx.reply("Приоритет должен быть от 1 до 5")
            return
        items = list(self.feature_requests)
        if fr_id <= 0 or fr_id > len(items):
            await ctx.reply("Фича-реквеста с таким номером не существует")
            return
        fr = items[fr_id - 1]
        if fr.author_id != ctx.user_id and not ctx.repository.is_admin(ctx.user_id):
            await ctx.reply("Вы не можете изменять приоритет этого фича-реквеста")
            return
        fr.priority = p
        await self.feature_requests.save()
        emoji = _PRIORITY_EMOJI.get(p, "⚪")
        await ctx.reply(f"Приоритет фича-реквеста #{fr_id} изменён на {emoji} {p}")

    @subcommand("<fr_id:int> note <text:rest>", description="Добавить примечание")
    async def add_note(self, ctx: FeatureContext, fr_id: int, text: str):
        text = text.strip()
        if not text:
            await ctx.reply("Укажите текст примечания")
            return
        items = list(self.feature_requests)
        if fr_id <= 0 or fr_id > len(items):
            await ctx.reply("Фича-реквеста с таким номером не существует")
            return
        fr = items[fr_id - 1]
        if fr.author_id != ctx.user_id and not ctx.repository.is_admin(ctx.user_id):
            await ctx.reply("Вы не можете добавлять примечания к этому фича-реквесту")
            return
        fr.notes.append(text)
        await self.feature_requests.save()
        await ctx.reply(f"Примечание добавлено к фича-реквесту #{fr_id}")

    @subcommand("<fr_id:int>", description="Просмотр")
    async def view(self, ctx: FeatureContext, fr_id: int):
        items = list(self.feature_requests)
        if fr_id <= 0 or fr_id > len(items):
            await ctx.reply("Фича-реквеста с таким номером не существует")
            return
        await ctx.reply(self._render_view(items[fr_id - 1]))

    @subcommand("done <ids:rest>", description="Сменить статус: done")
    async def cmd_done(self, ctx, ids):
        await self._batch_status(ctx, "done", ids.split())

    @subcommand("deny <ids:rest>", description="Сменить статус: deny")
    async def cmd_deny(self, ctx, ids):
        await self._batch_status(ctx, "deny", ids.split())

    @subcommand("reopen <ids:rest>", description="Сменить статус: reopen")
    async def cmd_reopen(self, ctx, ids):
        await self._batch_status(ctx, "reopen", ids.split())

    @subcommand("inprogress <ids:rest>", description="Сменить статус: inprogress")
    async def cmd_inprogress(self, ctx, ids):
        await self._batch_status(ctx, "inprogress", ids.split())

    @subcommand("testing <ids:rest>", description="Сменить статус: testing")
    async def cmd_testing(self, ctx, ids):
        await self._batch_status(ctx, "testing", ids.split())

    @subcommand("<text:rest>", description="Добавить фичу", catchall=True)
    async def add(self, ctx: FeatureContext, text: str):
        if ctx.message is None:
            return
        msg = ctx.message
        items = list(self.feature_requests)
        self.feature_requests.add(
            FeatureRequest(
                id=len(items) + 1,
                author_name=msg.from_user.name,
                text=text,
                author_id=msg.from_user.id,
                message_id=msg.message_id,
                chat_id=msg.chat_id,
                creation_timestamp=datetime.datetime.now().timestamp(),
            )
        )
        await self.feature_requests.save()
        await ctx.reply("Фича-реквест добавлен")

    @paginated("frs", per_page=15, header="Фича реквесты")
    def frs_page(self, ctx: FeatureContext, metadata: str):
        filter_type = _Filter(int(metadata))
        items = sorted(
            filter(_STATUS_FILTERS[filter_type], self.feature_requests.all()),
            key=lambda fr: fr.priority,
        )

        def fmt(fr: FeatureRequest):
            author = escape_markdown(fr.author_name)
            text = escape_markdown(fr.text)
            text = re.sub(r"@[a-zA-Z0-9]+", lambda m: f"`{m.group(0)}`", text)
            p = _PRIORITY_EMOJI.get(fr.priority, "⚪")
            return f"{p} `{author}`: {text}"

        def render(batch):
            return format_lined_list(items=[(fr.id, fmt(fr)) for fr in batch], delimiter=". ")

        extra = Keyboard.row(*[
            self.page_button("frs", label, metadata=str(f.value), page=0)
            for label, f in _FILTER_OPTIONS if f != filter_type
        ])
        return items, render, extra

    async def _batch_status(self, ctx: FeatureContext, cmd: str, ids: list[str]):
        if not ids:
            await ctx.reply("Укажите номера фичи-реквеста(ов)")
            return
        error_list, new_status = _STATUS_COMMANDS[cmd]
        results: list[tuple[int | str, str | None, str | None]] = []
        items = list(self.feature_requests)
        for raw in ids:
            if not raw.isdigit():
                results.append((raw, "Неверный номер фичи-реквеста", None))
                continue
            fid = int(raw)
            if fid <= 0 or fid > len(items):
                results.append((fid, "Фича-реквеста с таким номером не существует", None))
                continue
            fr = items[fid - 1]
            err = self._validate(ctx.user_id, fr, error_list)
            if err is not None:
                results.append((fr.id, err, None))
                continue
            fr.history.append(
                FeatureRequestChange(
                    author_id=ctx.user_id,
                    timestamp=datetime.datetime.now().timestamp(),
                    message_id=ctx.message.message_id if ctx.message else 0,
                    status=new_status,
                )
            )
            results.append((fr.id, None, fr.text))

        await self.feature_requests.save()
        results.sort(key=lambda x: x[1] is None)
        is_closing = new_status in [FeatureRequestStatus.DONE, FeatureRequestStatus.DENIED]
        formatted = []
        for fid, err, text in results:
            if err is None and text is not None and is_closing:
                ftext = re.sub("@[a-zA-Z0-9]+", lambda m: f"`{m.group(0)}`", text)
                formatted.append((fid, f"✅ {ftext}"))
            elif err is None:
                formatted.append((fid, "✅"))
            else:
                formatted.append((fid, err))
        await ctx.reply(format_lined_list(formatted))

    def _validate(self, user_id: int, fr: FeatureRequest, messages: list[str | None]):
        statuses = [
            FeatureRequestStatus.DONE,
            FeatureRequestStatus.DENIED,
            FeatureRequestStatus.OPEN,
            FeatureRequestStatus.IN_PROGRESS,
            FeatureRequestStatus.TESTING,
        ]
        for i, status in enumerate(statuses):
            if fr.status == status and messages[i] is not None:
                return messages[i]
        if fr.author_id != user_id and not self.repository.is_admin(user_id):
            return "Вы не можете редактировать статус этого фича-реквеста"
        return None

    def _render_view(self, fr: FeatureRequest) -> str:
        status_text = _STATUS_LABELS.get(fr.status, "Неизвестен")
        p_emoji = _PRIORITY_EMOJI.get(fr.priority, "⚪")
        text = re.sub(r"@[a-zA-Z0-9]+", lambda m: f"`{m.group(0)}`", escape_markdown(fr.text))
        author = escape_markdown(fr.author_name)
        date_str = ""
        if fr.creation_timestamp:
            dt = datetime.datetime.fromtimestamp(fr.creation_timestamp)
            date_str = f"\nДата: {dt.strftime('%d.%m.%Y %H:%M')}"
        history_text = ""
        if fr.history:
            history_text = "\n\nИстория изменений:"
            for change in fr.history:
                ch_dt = datetime.datetime.fromtimestamp(change.timestamp)
                ch_status = _STATUS_LABELS.get(change.status, "Неизвестен")
                history_text += f"\n• {ch_status} ({ch_dt.strftime('%d.%m.%Y %H:%M')})"
        notes_text = ""
        if fr.notes:
            notes_text = "\n\nПримечания:"
            for i, note in enumerate(fr.notes, 1):
                notes_text += f"\n{i}\\. {escape_markdown(note)}"
        return (
            f"Фича-реквест #{fr.id}\n"
            f"Статус: {status_text}\n"
            f"Приоритет: {p_emoji} {fr.priority}\n"
            f"Автор: `{author}`\n"
            f"Текст: {text}"
            f"{date_str}{history_text}{notes_text}"
        )

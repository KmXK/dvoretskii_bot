import datetime
import time

from steward.data.models.incident import Incident
from steward.framework import (
    Feature,
    FeatureContext,
    collection,
    paginated,
    subcommand,
)
from steward.helpers.formats import escape_markdown


def _format_when(ts: float) -> str:
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%d.%m %H:%M")


class IncidentFeature(Feature):
    command = "incident"
    description = "Зафиксировать инцидент в чате"
    help_examples = [
        "/incident упал прод в пятницу вечером",
        "/incident — показать список",
        "/incident remove 3 — удалить",
    ]

    incidents = collection("incidents")
    users = collection("users")

    @subcommand("", description="Список инцидентов чата")
    async def list_default(self, ctx: FeatureContext):
        await self.paginate(ctx, "incidents", metadata=str(ctx.chat_id))

    @subcommand("list", description="Список инцидентов")
    async def list_alias(self, ctx: FeatureContext):
        await self.paginate(ctx, "incidents", metadata=str(ctx.chat_id))

    @subcommand("remove <id:int>", description="Удалить инцидент")
    async def remove(self, ctx: FeatureContext, id: int):
        incident = self.incidents.find_by(id=id, chat_id=ctx.chat_id)
        if incident is None:
            await ctx.reply("Инцидент не найден")
            return
        if incident.author_id != ctx.user_id and ctx.user_id not in self.repository.db.admin_ids:
            await ctx.reply("Удалять может только автор или админ")
            return
        self.incidents.remove(incident)
        await self.incidents.save()
        await ctx.reply(f"Инцидент №{id} удалён")

    @subcommand("<text:rest>", description="Зафиксировать инцидент", catchall=True)
    async def add(self, ctx: FeatureContext, text: str):
        text = text.strip()
        if not text:
            await ctx.reply("Что за инцидент-то? Напиши после /incident описание")
            return
        incident = self.incidents.add(Incident(
            id=0,
            chat_id=ctx.chat_id,
            author_id=ctx.user_id,
            text=text,
            created_at=time.time(),
        ))
        await self.incidents.save()
        await ctx.reply(f"Инцидент №{incident.id} зафиксирован")

    @paginated("incidents", per_page=10, header="📋 Инциденты")
    def incidents_page(self, ctx: FeatureContext, metadata: str):
        chat_id = int(metadata)
        items = [i for i in self.incidents if i.chat_id == chat_id]
        items.sort(key=lambda i: i.created_at, reverse=True)

        def render(batch: list[Incident]) -> str:
            if not batch:
                return "Инцидентов пока нет"
            lines = []
            for inc in batch:
                author = self.users.find_by(id=inc.author_id)
                name = (
                    author.first_name or author.username if author else None
                ) or f"id{inc.author_id}"
                when = _format_when(inc.created_at)
                safe = escape_markdown(inc.text)
                lines.append(f"`{inc.id}`. {when} · {name}: {safe}")
            return "\n".join(lines)

        return items, render

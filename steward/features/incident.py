import datetime
import time

from telegram import MessageEntity

from steward.data.models.incident import (
    INCIDENT_STATUS_OPEN,
    INCIDENT_STATUS_RESOLVED,
    Incident,
)
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


def _is_open(inc: Incident) -> bool:
    return inc.status == INCIDENT_STATUS_OPEN


class IncidentFeature(Feature):
    command = "incident"
    description = "Зафиксировать инцидент в чате"
    help_examples = [
        "/incident упал прод в пятницу вечером",
        "/incident — показать список открытых",
        "/incident all — все инциденты",
        "/incident close 3 — закрыть",
        "/incident reopen 3 — переоткрыть",
        "/incident remove 3 — удалить",
    ]

    incidents = collection("incidents")
    users = collection("users")

    @subcommand("", description="Список открытых инцидентов чата")
    async def list_open(self, ctx: FeatureContext):
        await self.paginate(ctx, "incidents", metadata=f"{ctx.chat_id}:open")

    @subcommand("list", description="Список открытых")
    async def list_alias(self, ctx: FeatureContext):
        await self.paginate(ctx, "incidents", metadata=f"{ctx.chat_id}:open")

    @subcommand("all", description="Все инциденты (включая закрытые)")
    async def list_all(self, ctx: FeatureContext):
        await self.paginate(ctx, "incidents", metadata=f"{ctx.chat_id}:all")

    @subcommand("close <id:int>", description="Закрыть инцидент")
    async def close(self, ctx: FeatureContext, id: int):
        incident = self.incidents.find_by(id=id, chat_id=ctx.chat_id)
        if incident is None:
            await ctx.reply("Инцидент не найден")
            return
        if incident.status != INCIDENT_STATUS_OPEN:
            await ctx.reply("Инцидент уже закрыт")
            return
        if (
            incident.author_id != ctx.user_id
            and ctx.user_id not in self.repository.db.admin_ids
        ):
            await ctx.reply("Закрывать может только автор или админ")
            return
        incident.status = INCIDENT_STATUS_RESOLVED
        incident.closed_at = time.time()
        incident.closed_by = ctx.user_id
        await self.incidents.save()
        await ctx.reply(f"✅ Инцидент №{id} закрыт")

    @subcommand("reopen <id:int>", description="Переоткрыть закрытый")
    async def reopen(self, ctx: FeatureContext, id: int):
        incident = self.incidents.find_by(id=id, chat_id=ctx.chat_id)
        if incident is None:
            await ctx.reply("Инцидент не найден")
            return
        if incident.status == INCIDENT_STATUS_OPEN:
            await ctx.reply("Инцидент и так открыт")
            return
        if (
            incident.author_id != ctx.user_id
            and ctx.user_id not in self.repository.db.admin_ids
        ):
            await ctx.reply("Переоткрывать может только автор или админ")
            return
        incident.status = INCIDENT_STATUS_OPEN
        incident.closed_at = None
        incident.closed_by = None
        await self.incidents.save()
        await ctx.reply(f"🔁 Инцидент №{id} переоткрыт")

    @subcommand("remove <id:int>", description="Удалить инцидент")
    async def remove(self, ctx: FeatureContext, id: int):
        incident = self.incidents.find_by(id=id, chat_id=ctx.chat_id)
        if incident is None:
            await ctx.reply("Инцидент не найден")
            return
        if (
            incident.author_id != ctx.user_id
            and ctx.user_id not in self.repository.db.admin_ids
        ):
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

        mention = self._admin_mention()
        body = f"🚨 Инцидент №{incident.id} зафиксирован\n\n{escape_markdown(text)}"
        if mention:
            body = f"{body}\n\nЗовём {mention}"
        await ctx.reply(body)

    def _admin_mention(self) -> str:
        """Текстовое упоминание для созыва. Сначала пробуем @KmXKK
        (исторический владелец бота), иначе — первый админ из admin_ids."""
        preferred = next(
            (u for u in self.users if u.username and u.username.lower() == "kmxkk"),
            None,
        )
        if preferred:
            return f"@{preferred.username}"
        for admin_id in self.repository.db.admin_ids:
            user = self.users.find_by(id=admin_id)
            if user and user.username:
                return f"@{user.username}"
        return ""

    @paginated("incidents", per_page=10, header="📋 Инциденты")
    def incidents_page(self, ctx: FeatureContext, metadata: str):
        chat_str, _, mode = metadata.partition(":")
        chat_id = int(chat_str)
        mode = mode or "open"
        items = [i for i in self.incidents if i.chat_id == chat_id]
        if mode == "open":
            items = [i for i in items if _is_open(i)]
        items.sort(key=lambda i: i.created_at, reverse=True)

        header = "🚨 Открытые инциденты" if mode == "open" else "📋 Все инциденты"

        def render(batch: list[Incident]) -> str:
            if not batch:
                return (
                    "Открытых инцидентов нет 🎉"
                    if mode == "open"
                    else "Инцидентов пока нет"
                )
            lines = [header]
            for inc in batch:
                author = self.users.find_by(id=inc.author_id)
                name = (
                    author.first_name or author.username if author else None
                ) or f"id{inc.author_id}"
                when = _format_when(inc.created_at)
                marker = "🟥" if _is_open(inc) else "✅"
                safe = escape_markdown(inc.text)
                lines.append(f"{marker} `{inc.id}`. {when} · {name}: {safe}")
            return "\n".join(lines)

        return items, render

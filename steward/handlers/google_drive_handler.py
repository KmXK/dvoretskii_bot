from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.google_drive import is_available, list_drive_files

_CHUNK_SIZE = 4000


def _chunked(lines: list[str]) -> list[str]:
    chunks = []
    current: list[str] = []
    length = 0
    for line in lines:
        n = len(line) + 1
        if length + n > _CHUNK_SIZE:
            if current:
                chunks.append("\n".join(current))
            current = [line]
            length = n
        else:
            current.append(line)
            length += n
    if current:
        chunks.append("\n".join(current))
    return chunks


@CommandHandler("g", only_admin=True)
class GoogleDriveListHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not is_available():
            await context.message.reply_text("Google Drive не настроен")
            return True

        files = list_drive_files()
        if files is None:
            await context.message.reply_text(
                "Ошибка при получении списка файлов. Проверьте логи."
            )
            return True

        if not files:
            await context.message.reply_text("Файлы не найдены")
            return True

        lines = ["Файлы в Google Drive:"]
        for f in files:
            icon = "📁" if "folder" in f.get("mimeType", "") else "📄"
            name = f.get("name", "Без названия")
            fid = f.get("id", "")
            mime = f.get("mimeType", "")
            created = f.get("createdTime", "")
            lines.append(f"{icon} {name} (ID: {fid})")
            lines.append(f"   Тип: {mime}")
            if created:
                lines.append(f"   Создан: {created}")

        text = "\n".join(lines)
        if len(text) <= 4096:
            await context.message.reply_text(text)
        else:
            for chunk in _chunked(lines):
                await context.message.reply_text(chunk)
        return True

    def help(self):
        return "/g — показать файлы в Google Drive"

from steward.framework import Feature, FeatureContext, subcommand
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


class GoogleDriveFeature(Feature):
    command = "g"
    only_admin = True
    description = "Файлы в Google Drive"

    @subcommand("", description="Список файлов")
    async def list_files(self, ctx: FeatureContext):
        if not is_available():
            await ctx.reply("Google Drive не настроен")
            return
        files = list_drive_files()
        if files is None:
            await ctx.reply("Ошибка при получении списка файлов. Проверьте логи.")
            return
        if not files:
            await ctx.reply("Файлы не найдены")
            return
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
            await ctx.reply(text)
        else:
            for chunk in _chunked(lines):
                await ctx.reply(chunk)

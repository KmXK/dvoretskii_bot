from telegram import InputFile

from steward.framework import Feature, FeatureContext, subcommand


class DbFeature(Feature):
    command = "db"
    only_admin = True
    description = "Отправить файл db.json"

    TARGET_CHAT_ID = -1003876657662

    @subcommand("", description="Отправить db.json в спецчат")
    async def send_db(self, ctx: FeatureContext):
        if ctx.chat_id != self.TARGET_CHAT_ID:
            return False
        try:
            with open("db.json", "rb") as f:
                await ctx.bot.send_document(
                    chat_id=self.TARGET_CHAT_ID,
                    document=InputFile(f, filename="db.json"),
                )
            await ctx.reply("Файл db.json отправлен")
        except FileNotFoundError:
            await ctx.reply("Файл db.json не найден")
        except Exception as e:
            await ctx.reply(f"Ошибка при отправке файла: {e}")

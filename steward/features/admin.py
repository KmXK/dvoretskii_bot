from steward.framework import Feature, FeatureContext, collection, subcommand


class AdminFeature(Feature):
    command = "admin"
    only_admin = True
    description = "Управление админами"

    admin_ids = collection("admin_ids")

    @subcommand("", description="Список админов")
    async def view(self, ctx: FeatureContext):
        ids = sorted(self.admin_ids.all())
        if not ids:
            await ctx.reply("Админов нет")
            return
        await ctx.reply("\n".join(["Админы:", "", *(str(i) for i in ids)]))

    @subcommand("add <id:int>", description="Добавить админа")
    async def add(self, ctx: FeatureContext, id: int):
        if not self.admin_ids.add(id):
            await ctx.reply("Такой админ уже есть")
            return
        await self.admin_ids.save()
        await ctx.reply(f"Админ с id = {id} добавлен")

    @subcommand("remove <id:int>", description="Удалить админа")
    async def remove(self, ctx: FeatureContext, id: int):
        if not self.admin_ids.remove(id):
            await ctx.reply("Ошибка. Админа с таким id не существует")
            return
        await self.admin_ids.save()
        await ctx.reply(f"Админ с id = {id} удалён")

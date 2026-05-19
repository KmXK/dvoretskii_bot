from steward.framework import Feature, FeatureContext, collection, subcommand


class AdminFeature(Feature):
    command = "admin"
    only_admin = True
    description = "Управление админами"

    admin_ids = collection("admin_ids")
    users = collection("users")

    def _display(self, user_id: int) -> str:
        user = self.users.find_by(id=user_id)
        if user and user.username:
            return f"@{user.username}"
        return str(user_id)

    def _resolve(self, target: str) -> tuple[int | None, str]:
        if target.startswith("@"):
            username = target[1:]
            user = self.users.find_one(
                lambda u: u.username and u.username.lower() == username.lower()
            )
            if user is None:
                return None, f"Пользователь {target} не найден. Попроси его написать что-нибудь в чат."
            return user.id, ""
        try:
            return int(target), ""
        except ValueError:
            return None, "Неверный формат: укажи @username или числовой ID"

    @subcommand("", description="Список админов")
    async def view(self, ctx: FeatureContext):
        ids = sorted(self.admin_ids.all())
        if not ids:
            await ctx.reply("Админов нет")
            return
        lines = [self._display(uid) for uid in ids]
        await ctx.reply("\n".join(["Админы:", "", *lines]))

    @subcommand("add <target:str>", description="Добавить админа (@username или id)")
    async def add(self, ctx: FeatureContext, target: str):
        user_id, error = self._resolve(target)
        if user_id is None:
            await ctx.reply(error)
            return
        if not self.admin_ids.add(user_id):
            await ctx.reply("Такой админ уже есть")
            return
        await self.admin_ids.save()
        await ctx.reply(f"Админ {self._display(user_id)} добавлен")

    @subcommand("remove <target:str>", description="Удалить админа (@username или id)")
    async def remove(self, ctx: FeatureContext, target: str):
        user_id, error = self._resolve(target)
        if user_id is None:
            await ctx.reply(error)
            return
        if not self.admin_ids.remove(user_id):
            await ctx.reply("Ошибка. Админа с таким id не существует")
            return
        await self.admin_ids.save()
        await ctx.reply(f"Админ {self._display(user_id)} удалён")

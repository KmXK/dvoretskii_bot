from dataclasses import dataclass

from steward.bot.context import ChatBotContext
from steward.handlers.handler import Handler
from steward.helpers.command_validation import ValidationArgumentsError, validate_arguments, validate_command_msg


@dataclass
class PendingStandAdd:
    stand_name: str
    description: str | None = None
    step: str = "description"


class StandsHandler(Handler):
    def __init__(self):
        self._pending_add: dict[int, PendingStandAdd] = {}

    async def chat(self, context: ChatBotContext):
        user_id = context.message.from_user.id
        message_text = context.message.text or ""

        pending = self._pending_add.get(user_id)
        if pending and not message_text.startswith("/"):
            if not message_text:
                await context.message.reply_text("Пришли текстовое сообщение.")
                return True
            return await self._handle_pending_add(context, pending)

        validation = validate_command_msg(
            context.update,
            "stands",
            r"(?P<args>.*)?",
        )
        if not validation:
            return False

        args = (validation.args or {}).get("args", "") or ""
        args = args.strip()
        if args == "":
            await context.message.reply_text(self._build_stands_list())
            return True

        add_args = validate_arguments(args, r"add\s+(?P<name>.+)")
        if add_args is not None:
            return await self._start_add_flow(context, add_args["name"])

        remove_args = validate_arguments(args, r"remove\s+(?P<name>.+)")
        if remove_args is not None:
            return await self._remove_stand(context, remove_args["name"])

        raise ValidationArgumentsError()

    async def _start_add_flow(self, context: ChatBotContext, stand_name_raw: str):
        stand_name = stand_name_raw.strip()
        if not stand_name:
            raise ValidationArgumentsError()

        existing = self._find_user_by_stand_name(stand_name)
        if existing is not None:
            await context.message.reply_text(
                f"Пользователь «{stand_name}» уже привязан к @{existing.username or existing.id}",
            )
            return True

        self._pending_add[context.message.from_user.id] = PendingStandAdd(
            stand_name=stand_name,
        )
        await context.message.reply_text(
            f"Добавляем пользователя «{stand_name}».\nПришли описание пользователя одним сообщением.",
        )
        return True

    async def _handle_pending_add(self, context: ChatBotContext, pending: PendingStandAdd):
        text = context.message.text.strip()
        user_id = context.message.from_user.id
        if not text:
            await context.message.reply_text("Сообщение пустое, пришли текст.")
            return True

        if pending.step == "description":
            pending.description = text
            pending.step = "user"
            await context.message.reply_text(
                "Теперь укажи владельца (@username или user_id).",
            )
            return True

        target_user = self._find_user_by_identifier(text)
        if target_user is None:
            await context.message.reply_text(
                "Пользователь не найден. Укажи @username или user_id.",
            )
            return True

        assert pending.description is not None
        if target_user.stand_name and target_user.stand_name.strip():
            await context.message.reply_text(
                f"У @{target_user.username or target_user.id} уже есть пользователь «{target_user.stand_name}».",
            )
            self._pending_add.pop(user_id, None)
            return True

        same_stand_user = self._find_user_by_stand_name(pending.stand_name)
        if same_stand_user is not None and same_stand_user.id != target_user.id:
            await context.message.reply_text(
                f"Пользователь «{pending.stand_name}» уже привязан к другому владельцу.",
            )
            self._pending_add.pop(user_id, None)
            return True

        target_user.stand_name = pending.stand_name
        target_user.stand_description = pending.description
        await self.repository.save()
        self._pending_add.pop(user_id, None)
        await context.message.reply_text(
            f"Готово. Пользователь «{target_user.stand_name}» сохранен для @{target_user.username or target_user.id}.",
        )
        return True

    async def _remove_stand(self, context: ChatBotContext, stand_name_raw: str):
        stand_name = stand_name_raw.strip()
        if not stand_name:
            raise ValidationArgumentsError()

        user = self._find_user_by_stand_name(stand_name)
        if user is None:
            await context.message.reply_text(f"Пользователь «{stand_name}» не найден.")
            return True

        user.stand_name = None
        user.stand_description = None
        await self.repository.save()
        await context.message.reply_text(f"Пользователь «{stand_name}» удален.")
        return True

    def _build_stands_list(self) -> str:
        stands = []
        for user in self.repository.db.users:
            if not user.stand_name or not user.stand_description:
                continue
            owner = f"@{user.username}" if user.username else str(user.id)
            stands.append((user.stand_name.strip(), user.stand_description.strip(), owner))

        if not stands:
            return "Пользователей пока нет."

        stands.sort(key=lambda x: x[0].lower())
        lines = ["Пользователи:"]
        for name, description, owner in stands:
            lines.append(f"- {name}: {description} ({owner})")
        return "\n".join(lines)

    def _find_user_by_stand_name(self, stand_name: str):
        target = stand_name.strip().lower()
        for user in self.repository.db.users:
            if user.stand_name and user.stand_name.strip().lower() == target:
                return user
        return None

    def _find_user_by_identifier(self, identifier: str):
        value = identifier.strip()
        if value.startswith("@"):
            value = value[1:]
        if value == "":
            return None

        if value.isdigit():
            user_id = int(value)
            return next((u for u in self.repository.db.users if u.id == user_id), None)

        target_username = value.lower()
        return next(
            (
                u
                for u in self.repository.db.users
                if u.username and u.username.lower() == target_username
            ),
            None,
        )

    def help(self):
        return "/stands - посмотреть/добавить/удалить пользователей"

    def prompt(self):
        return (
            "▶ /stands — управление пользователями\n"
            "  Просмотр: /stands\n"
            "  Добавить: /stands add <имя_пользователя>\n"
            "  Удалить: /stands remove <имя_пользователя>\n"
            "  Примеры:\n"
            "  - «покажи всех пользователей» → /stands\n"
            "  - «добавь пользователя Star Platinum» → /stands add Star Platinum\n"
            "  - «удали пользователя Star Platinum» → /stands remove Star Platinum"
        )

import logging
import re
import uuid
from dataclasses import dataclass, field
from time import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity

from steward.bot.context import CallbackBotContext, ChatBotContext
from steward.handlers.handler import Handler
from steward.helpers.ai import get_prompt, make_yandex_ai_query
from steward.helpers.command_validation import ValidationArgumentsError
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)

ROUTER_PROMPT = get_prompt("router")

TRIGGERS = ["дворецкий", "уважаемый"]
CB_PREFIX = "ai_route|"
MAX_PENDING = 100


@dataclass
class PendingExecution:
    commands: list[str]
    context: ChatBotContext
    user_id: int
    created_at: float = field(default_factory=time)


_pending: dict[str, PendingExecution] = {}


def _cleanup_pending():
    if len(_pending) <= MAX_PENDING:
        return
    entries = sorted(_pending.items(), key=lambda x: x[1].created_at)
    for key, _ in entries[: len(entries) - MAX_PENDING]:
        del _pending[key]


class AiRouterHandler(Handler):
    def __init__(self, handlers: list[Handler]):
        self._handlers = handlers

    async def chat(self, context: ChatBotContext):
        if not context.message or not context.message.text:
            return False

        if context.message.text.startswith("/"):
            return False

        user_request, matched = self._extract_request(
            context.message.text, context.bot.username
        )
        if not matched and context.message.reply_to_message:
            if self._is_bot_message(context.message.reply_to_message, context.bot):
                user_request = context.message.text
                matched = True
        if not matched or not user_request:
            return False

        reply_text = ""
        reply_context = ""
        if context.message.reply_to_message:
            reply_msg = context.message.reply_to_message
            parts = []

            sender_info = self._extract_sender_info(reply_msg)
            if sender_info:
                parts.append(f"Отправитель: {sender_info}")

            if reply_msg.text:
                reply_text = reply_msg.text
                parts.append(f"Текст: {self._restructure_debt_table(reply_text)}")

            reply_context = "\n".join(parts)

        if reply_text and "Кто кому должен" in reply_text:
            pay_commands = self._try_generate_pay_commands(user_request, reply_text)
            if pay_commands is not None:
                commands = pay_commands
                return await self._present_commands(context, commands, user_request)

        commands_info, prompts_info = self._build_commands_info(
            context.message.from_user.id
        )
        prompt = ROUTER_PROMPT.format(commands=commands_info, prompts=prompts_info)

        check_limit("ai_router", 15, Duration.MINUTE)
        check_limit(
            "ai_router_user",
            5,
            30 * Duration.SECOND,
            name=str(context.message.from_user.id),
        )

        ai_input = user_request
        if reply_context:
            ai_input = f"Контекст сообщения: {reply_context}\n\nЗапрос: {user_request}"

        try:
            response = await make_yandex_ai_query(
                context.message.from_user.id,
                [("user", ai_input)],
                prompt,
            )
        except Exception as e:
            logger.exception("AI router query failed: %s", e)
            return False

        response = response.strip().strip("`")
        if response.startswith("```"):
            response = re.sub(r"```\w*\n?", "", response).strip()

        commands: list[str] = []
        for line in response.split("\n"):
            stripped = line.strip()
            if stripped.startswith("/"):
                commands.append(stripped)
            elif commands and stripped:
                commands[-1] += "\n" + stripped

        if not commands:
            return await self._fallback_to_ai(context, user_request)

        return await self._present_commands(context, commands, user_request)

    async def _present_commands(
        self,
        context: ChatBotContext,
        commands: list[str],
        user_request: str,
    ) -> bool:
        user_id = context.message.from_user.id
        allowed = self._get_allowed_command_names(user_id)
        commands = [
            cmd
            for cmd in commands
            if cmd.split()[0].lstrip("/").split("@")[0].lower() in allowed
        ]

        if not commands:
            await context.message.reply_text(
                "⛔ У вас нет прав для выполнения этих команд"
            )
            return True

        key = uuid.uuid4().hex[:12]
        _pending[key] = PendingExecution(
            commands=commands,
            context=context,
            user_id=context.message.from_user.id,
        )
        _cleanup_pending()

        commands_text = "\n".join(
            f"```\n{cmd}\n```" if "\n" in cmd else f"`{cmd}`" for cmd in commands
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Выполнить",
                        callback_data=f"{CB_PREFIX}ok|{key}",
                    ),
                    InlineKeyboardButton(
                        "❌ Отмена",
                        callback_data=f"{CB_PREFIX}no|{key}",
                    ),
                ]
            ]
        )

        await context.message.reply_text(
            f"🤖 {commands_text}",
            parse_mode="markdown",
            reply_markup=keyboard,
        )
        return True

    async def callback(self, context: CallbackBotContext):
        data = context.callback_query.data
        if not data or not data.startswith(CB_PREFIX):
            return False

        parts = data[len(CB_PREFIX) :].split("|", 1)
        if len(parts) != 2:
            return False

        action, key = parts
        pending = _pending.get(key)

        if pending is None:
            await context.callback_query.answer("Запрос устарел")
            await context.callback_query.message.edit_reply_markup(reply_markup=None)
            return True

        if context.callback_query.from_user.id != pending.user_id:
            await context.callback_query.answer("Только автор может подтвердить")
            return True

        del _pending[key]

        if action == "no":
            await context.callback_query.message.edit_text("❌ Отменено")
            await context.callback_query.answer()
            return True

        if action == "ok":
            await context.callback_query.message.delete()
            await context.callback_query.answer()

            for command in pending.commands:
                self._patch_message(pending.context.message, command)
                for handler in self._handlers:
                    if handler is self:
                        continue
                    if handler.only_for_admin and not self.repository.is_admin(
                        pending.user_id
                    ):
                        continue
                    try:
                        if hasattr(handler, "chat") and await handler.chat(
                            pending.context
                        ):
                            break
                    except ValidationArgumentsError:
                        continue
                    except Exception as e:
                        logger.debug("Handler %s: %s", handler.__class__.__name__, e)
            return True

        return False

    @staticmethod
    def _extract_sender_info(message) -> str:
        origin = getattr(message, "forward_origin", None)
        if origin is not None:
            if hasattr(origin, "sender_user") and origin.sender_user:
                user = origin.sender_user
                if user.username:
                    return f"@{user.username} (id: {user.id})"
                name = user.first_name or ""
                if user.last_name:
                    name += f" {user.last_name}"
                return f"{name} (id: {user.id})"
            if hasattr(origin, "sender_user_name"):
                return origin.sender_user_name

        if message.from_user:
            user = message.from_user
            if user.username:
                return f"@{user.username} (id: {user.id})"
            name = user.first_name or ""
            if user.last_name:
                name += f" {user.last_name}"
            return f"{name} (id: {user.id})"

        return ""

    async def _fallback_to_ai(
        self, context: ChatBotContext, user_request: str
    ) -> bool:
        self._patch_message(context.message, f"/ai {user_request}")
        for handler in self._handlers:
            if handler is self:
                continue
            try:
                if hasattr(handler, "chat") and await handler.chat(context):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _is_bot_message(message, bot) -> bool:
        if message.from_user and message.from_user.id == bot.id:
            return True
        origin = getattr(message, "forward_origin", None)
        if origin and hasattr(origin, "sender_user") and origin.sender_user:
            return origin.sender_user.id == bot.id
        return False

    @staticmethod
    def _parse_debt_table(text: str) -> list[tuple[str, str, str]]:
        debts: list[tuple[str, str, str]] = []
        in_table = False
        for line in text.split("\n"):
            stripped = line.strip()
            if "Кто кому должен" in stripped:
                in_table = True
                continue
            if in_table:
                if "Должник" in stripped and "Кому" in stripped:
                    continue
                if stripped.startswith("-"):
                    continue
                if not stripped or stripped.startswith(
                    ("📊", "💸", "💳", "🔗", "/")
                ):
                    in_table = False
                    continue
                parts = re.split(r"\s{2,}", stripped)
                if len(parts) >= 3:
                    debts.append((parts[0], parts[1], parts[2]))
        return debts

    @staticmethod
    def _try_generate_pay_commands(
        user_request: str, reply_text: str
    ) -> list[str] | None:
        request_lower = user_request.lower().strip()
        pay_patterns = [
            r"^(\S+)\s+(?:всем\s+)?(?:заплатил|оплатил|рассчитался|отдал)",
            r"^(\S+)\s+(?:никому\s+)?(?:не\s+)?(?:больше\s+)?(?:не\s+)?должен",
            r"^(\S+)\s+(?:закрыл|погасил)",
        ]
        person = None
        for pattern in pay_patterns:
            m = re.search(pattern, request_lower)
            if m:
                person = m.group(1)
                break
        if not person:
            return None

        debts = AiRouterHandler._parse_debt_table(reply_text)
        if not debts:
            return None

        commands = []
        for debtor, creditor, amount_str in debts:
            if debtor.lower() == person:
                clean = amount_str.strip().replace(",", ".").replace("\u00a0", "").replace(" ", "")
                try:
                    amount = float(clean)
                    commands.append(f"/bill pay {debtor} {creditor} {amount:g}")
                except ValueError:
                    continue

        return commands if commands else None

    @staticmethod
    def _restructure_debt_table(text: str) -> str:
        if "Кто кому должен" not in text:
            return text
        lines = text.split("\n")
        result = []
        in_table = False
        for line in lines:
            stripped = line.strip()
            if "Кто кому должен" in stripped:
                in_table = True
                result.append(line)
                continue
            if in_table:
                if "Должник" in stripped and "Кому" in stripped:
                    continue
                if stripped.startswith("-"):
                    continue
                if not stripped or stripped.startswith(
                    ("📊", "💸", "💳", "🔗", "/")
                ):
                    in_table = False
                    result.append(line)
                    continue
                parts = re.split(r"\s{2,}", stripped)
                if len(parts) >= 3:
                    result.append(f"{parts[0]} должен {parts[1]}: {parts[2]}")
                else:
                    result.append(line)
                continue
            result.append(line)
        return "\n".join(result)

    def _extract_request(self, text: str, bot_username: str | None) -> tuple[str, bool]:
        text_lower = text.lower()

        if bot_username and text_lower.startswith(f"@{bot_username.lower()}"):
            return text[len(bot_username) + 1 :].strip(" ,:"), True

        for trigger in TRIGGERS:
            if text_lower.startswith(trigger):
                return text[len(trigger) :].strip(" ,:"), True

        return "", False

    def _get_allowed_command_names(self, user_id: int) -> set[str]:
        """Возвращает множество имён команд, доступных пользователю."""
        names: set[str] = set()
        for handler in self._handlers:
            if handler.only_for_admin and not self.repository.is_admin(user_id):
                continue
            h = handler.help()
            if h and h.startswith("/"):
                names.add(h.split()[0].lstrip("/").split("@")[0].lower())
        return names

    def _build_commands_info(self, user_id: int) -> tuple[str, str]:
        helps = []
        prompts = []
        for handler in self._handlers:
            if handler.only_for_admin and not self.repository.is_admin(user_id):
                continue
            h = handler.help()
            if h:
                helps.append(h)
            p = handler.prompt()
            if p:
                prompts.append(p)
        helps.sort()
        return "\n".join(helps), "\n\n".join(prompts)

    @staticmethod
    def _patch_message(message, command: str):
        cmd_part = command.split()[0]
        entity = MessageEntity(
            type=MessageEntity.BOT_COMMAND,
            offset=0,
            length=len(cmd_part),
        )

        was_frozen = getattr(message, "_frozen", False)
        if was_frozen:
            object.__setattr__(message, "_frozen", False)

        message.text = command
        message.entities = (entity,)

        if was_frozen:
            object.__setattr__(message, "_frozen", True)

    def help(self):
        return None

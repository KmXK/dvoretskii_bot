import logging

from telegram.error import ChatMigrated

from steward.bot.context import ChatBotContext
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step

logger = logging.getLogger(__name__)


def _parse_chat_names(text):
    names = []
    i = 0
    while i < len(text):
        if text[i] == "(":
            depth = 1
            start = i + 1
            i += 1
            while i < len(text) and depth > 0:
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                i += 1
            if depth == 0:
                name = text[start : i - 1].strip()
                if name:
                    names.append(name)
        else:
            i += 1
    return names


class BroadcastStep(Step):
    async def chat(self, context):
        if not context.session_context.get("initialized"):
            context.session_context["initialized"] = True

            chat_names = context.session_context["chat_names"]
            chats_db = context.repository.db.chats

            target_chats = []
            not_found = []

            for name in chat_names:
                found = next(
                    (
                        c
                        for c in chats_db
                        if c.name.lower() == name.strip().lower() and c.id < 0
                    ),
                    None,
                )
                if found:
                    target_chats.append(found)
                else:
                    not_found.append(name)

            if not target_chats:
                await context.message.reply_text(
                    "Не найдено ни одного подходящего группового чата"
                )
                return True

            context.session_context["target_chats"] = [c.id for c in target_chats]

            found_names = ", ".join(c.name for c in target_chats)
            text = f"Трансляция начата в: {found_names}"
            if not_found:
                text += f"\nНе найдены: {', '.join(not_found)}"
            text += "\n\n/broadcast stop — завершить"

            await context.message.reply_text(text)
            return False

        if context.message.text and validate_command_msg(context.update, "broadcast"):
            entity_len = context.update.effective_message.entities[0].length
            args = context.message.text[entity_len:].strip()
            if args.lower() == "stop":
                await context.message.reply_text("Трансляция завершена")
                return True

        errors = []
        target_chats = context.session_context["target_chats"]
        for i, chat_id in enumerate(target_chats):
            try:
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=context.message.chat.id,
                    message_id=context.message.message_id,
                )
            except ChatMigrated as e:
                new_id = e.new_chat_id
                target_chats[i] = new_id
                for c in context.repository.db.chats:
                    if c.id == chat_id:
                        c.id = new_id
                        break
                await context.repository.save()
                try:
                    await context.bot.copy_message(
                        chat_id=new_id,
                        from_chat_id=context.message.chat.id,
                        message_id=context.message.message_id,
                    )
                except Exception:
                    logger.exception("Broadcast to migrated %s failed", new_id)
                    errors.append(str(new_id))
            except Exception:
                logger.exception("Broadcast to %s failed", chat_id)
                chat = next(
                    (c for c in context.repository.db.chats if c.id == chat_id),
                    None,
                )
                errors.append(chat.name if chat else str(chat_id))

        if errors:
            await context.message.reply_text(f"Ошибка отправки в: {', '.join(errors)}")

        return False

    async def callback(self, context):
        return False


class BroadcastSessionHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__([BroadcastStep()])

    def try_activate_session(self, update, session_context):
        if not update.message or not update.message.text:
            return False

        if not validate_command_msg(update, "broadcast"):
            return False

        entity_len = update.message.entities[0].length
        args = update.message.text[entity_len:].strip()

        if args.lower() == "stop":
            return False

        chat_names = _parse_chat_names(args)
        if not chat_names:
            return False

        session_context["chat_names"] = chat_names
        return True

    async def on_session_finished(self, update, session_context):
        pass

    async def on_stop(self, update, context):
        if update.effective_message:
            await update.effective_message.reply_text("Трансляция завершена")

    def help(self):
        return "/broadcast (чат 1) (чат 2) — трансляция сообщений в чаты"


USAGE_TEXT = "Использование: /broadcast (чат 1) (чат 2)\n/broadcast stop — завершить"


class BroadcastUsageHandler(Handler):
    only_for_admin = True

    async def chat(self, context: ChatBotContext):
        if not context.message or not context.message.text:
            return False

        if not validate_command_msg(context.update, "broadcast"):
            return False

        await context.message.reply_text(USAGE_TEXT)
        return True

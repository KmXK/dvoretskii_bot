import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import ChatMigrated

from steward.helpers.command_validation import validate_command_msg
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step

logger = logging.getLogger(__name__)

PREFIX = "broadcast_select|"
DONE_CB = "broadcast_select|done"
STOP_CB = "broadcast_select|stop"


def _get_user_group_chats(context):
    user_id = context.update.effective_user.id
    user = next((u for u in context.repository.db.users if u.id == user_id), None)
    if not user:
        return []

    chat_ids = set(getattr(user, "chat_ids", []) or [])
    seen = set()
    result = []
    for c in context.repository.db.chats:
        if c.id < 0 and c.id in chat_ids and c.id not in seen:
            seen.add(c.id)
            result.append(c)
    return result


def _build_select_keyboard(chats, selected_ids):
    rows = []
    for chat in chats:
        mark = "✅" if chat.id in selected_ids else "☐"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{mark} {chat.name}",
                    callback_data=f"{PREFIX}{chat.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Начать трансляцию ➜", callback_data=DONE_CB)])
    return InlineKeyboardMarkup(rows)


def _build_stop_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏹ Завершить трансляцию", callback_data=STOP_CB)]]
    )


class BroadcastStep(Step):
    async def chat(self, context):
        if context.session_context.get("broadcasting"):
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
                await context.message.reply_text(
                    f"Ошибка отправки в: {', '.join(errors)}"
                )

            return False

        chats = _get_user_group_chats(context)
        if not chats:
            await context.message.reply_text("У вас нет доступных групповых чатов")
            return True

        context.session_context["available_chats"] = chats
        context.session_context["selected_ids"] = set()

        await context.message.reply_text(
            "Выберите чаты для трансляции:",
            reply_markup=_build_select_keyboard(chats, set()),
        )
        return False

    async def callback(self, context):
        data = context.callback_query.data
        if not data or not data.startswith(PREFIX):
            return False

        if data == STOP_CB:
            await context.callback_query.edit_message_text("Трансляция завершена")
            await context.callback_query.answer()
            return True

        if context.session_context.get("broadcasting"):
            return False

        if data == DONE_CB:
            selected = context.session_context.get("selected_ids", set())
            if not selected:
                await context.callback_query.answer("Выберите хотя бы один чат")
                return False

            context.session_context["target_chats"] = list(selected)
            context.session_context["broadcasting"] = True

            chats = context.session_context["available_chats"]
            names = ", ".join(c.name for c in chats if c.id in selected)

            await context.callback_query.edit_message_text(
                f"Трансляция начата в: {names}",
                reply_markup=_build_stop_keyboard(),
            )
            await context.callback_query.answer()
            return False

        chat_id = int(data[len(PREFIX) :])
        selected = context.session_context.get("selected_ids", set())
        if chat_id in selected:
            selected.discard(chat_id)
        else:
            selected.add(chat_id)
        context.session_context["selected_ids"] = selected

        chats = context.session_context["available_chats"]
        await context.callback_query.edit_message_reply_markup(
            reply_markup=_build_select_keyboard(chats, selected),
        )
        await context.callback_query.answer()
        return False


class BroadcastSessionHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__([BroadcastStep()])

    def try_activate_session(self, update, session_context):
        if not update.message or not update.message.text:
            return False

        if not validate_command_msg(update, "broadcast"):
            return False

        return True

    async def on_session_finished(self, update, session_context):
        pass

    async def on_stop(self, update, context):
        if update.effective_message:
            await update.effective_message.reply_text("Трансляция завершена")

    def help(self):
        return "/broadcast — трансляция сообщений в выбранные чаты"

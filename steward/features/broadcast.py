import logging

from telegram.error import ChatMigrated

from steward.framework import (
    Button,
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    step,
    subcommand,
    wizard,
)
from steward.session.step import Step

logger = logging.getLogger(__name__)


_PREFIX = "broadcast_select|"
_DONE_CB = "broadcast_select|done"
_STOP_CB = "broadcast_select|stop"


def _user_group_chats(repository, user_id):
    user = next((u for u in repository.db.users if u.id == user_id), None)
    if not user:
        return []
    chat_ids = set(getattr(user, "chat_ids", []) or [])
    seen = set()
    result = []
    for c in repository.db.chats:
        if c.id < 0 and c.id in chat_ids and c.id not in seen:
            seen.add(c.id)
            result.append(c)
    return result


def _select_keyboard(chats, selected_ids):
    kb = Keyboard([])
    for chat in chats:
        mark = "✅" if chat.id in selected_ids else "☐"
        kb.append_row(Button(f"{mark} {chat.name}", callback_data=f"{_PREFIX}{chat.id}"))
    kb.append_row(Button("Начать трансляцию ➜", callback_data=_DONE_CB))
    return kb


def _stop_keyboard():
    return Keyboard.row(Button("⏹ Завершить трансляцию", callback_data=_STOP_CB))


class _BroadcastStep(Step):
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
                await context.message.reply_text(f"Ошибка отправки в: {', '.join(errors)}")
            return False

        chats = _user_group_chats(context.repository, context.update.effective_user.id)
        if not chats:
            await context.message.reply_text("У вас нет доступных групповых чатов")
            return True
        context.session_context["available_chats"] = chats
        context.session_context["selected_ids"] = set()
        await context.message.reply_text(
            "Выберите чаты для трансляции:",
            reply_markup=_select_keyboard(chats, set()).to_markup(),
        )
        return False

    async def callback(self, context):
        data = context.callback_query.data
        if not data or not data.startswith(_PREFIX):
            return False

        if data == _STOP_CB:
            await context.callback_query.edit_message_text("Трансляция завершена")
            await context.callback_query.answer()
            return True

        if context.session_context.get("broadcasting"):
            return False

        if data == _DONE_CB:
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
                reply_markup=_stop_keyboard().to_markup(),
            )
            await context.callback_query.answer()
            return False

        chat_id = int(data[len(_PREFIX):])
        selected = context.session_context.get("selected_ids", set())
        if chat_id in selected:
            selected.discard(chat_id)
        else:
            selected.add(chat_id)
        context.session_context["selected_ids"] = selected
        chats = context.session_context["available_chats"]
        await context.callback_query.edit_message_reply_markup(
            reply_markup=_select_keyboard(chats, selected).to_markup(),
        )
        await context.callback_query.answer()
        return False

    def stop(self):
        pass


class BroadcastFeature(Feature):
    command = "broadcast"
    description = "Трансляция сообщений в выбранные чаты"

    chats = collection("chats")
    users = collection("users")

    @subcommand("", description="Начать выбор чатов")
    async def start(self, ctx: FeatureContext):
        await self.start_wizard("broadcast:run", ctx)

    @wizard("broadcast:run", step("broadcast", _BroadcastStep()))
    async def on_done(self, ctx: FeatureContext, **state):
        pass

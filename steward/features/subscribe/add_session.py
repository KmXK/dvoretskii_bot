import logging
from datetime import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.delayed_action.channel_subscription import get_posts_from_html
from steward.features.subscribe.parsing import parse_time_input
from steward.session.step import Step

logger = logging.getLogger(__name__)


class CollectChannelPostStep(Step):
    def __init__(self):
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            await context.message.reply_text(
                "Отправьте мне любой пост из канала, на который хотите подписаться"
            )
            self.is_waiting = True
            return False

        if not context.message.forward_origin:
            await context.message.reply_text(
                "Это сообщение не переслано из канала. Пожалуйста, перешлите пост из канала."
            )
            return False

        if not hasattr(context.message.forward_origin, "chat"):
            await context.message.reply_text(
                "Это сообщение не переслано из канала. Пожалуйста, перешлите пост из канала."
            )
            return False

        forward_chat = context.message.forward_origin.chat
        if forward_chat.type != "channel":
            await context.message.reply_text(
                "Это не канал. Пожалуйста, перешлите пост из канала."
            )
            return False

        context.session_context["channel_info"] = {
            "channel_id": forward_chat.id,
            "channel_username": forward_chat.username or "",
        }
        self.is_waiting = False
        return True

    async def callback(self, context):
        return False

    def stop(self):
        self.is_waiting = False


class VerifyChannelStep(Step):
    def __init__(self):
        self.is_waiting = False

    async def chat(self, context):
        if not self.is_waiting:
            channel_info = context.session_context["channel_info"]
            channel_id = channel_info["channel_id"]
            channel_username = channel_info["channel_username"]

            if not channel_username:
                await context.message.reply_text(
                    "У канала нет username, невозможно получить посты из канала"
                )
                return True

            try:
                channel_entity = await context.client.get_input_entity(channel_username)
                posts = await get_posts_from_html(channel_username)
                if posts:
                    last_post = posts[-1]
                    message = await context.client.get_messages(
                        channel_entity, ids=last_post["id"]
                    )
                    if message:
                        await context.message.chat.send_message(
                            "Это последнее сообщение из канала:"
                        )
                        await context.client.forward_messages(
                            context.message.chat_id,
                            message,
                            from_peer=channel_entity,
                        )
                else:
                    await context.message.reply_text(
                        "Не удалось получить последнее сообщение из канала"
                    )
                    return True
            except Exception as e:
                logger.exception(e)
                await context.message.reply_text(
                    f"Ошибка при получении последнего сообщения: {str(e)}"
                )
                return True

            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "Да, это оно",
                        callback_data="subscribe_handler|confirm_channel",
                    ),
                    InlineKeyboardButton(
                        "Нет, это не оно",
                        callback_data="subscribe_handler|reject_channel",
                    ),
                ],
            ])
            await context.message.reply_text(
                "Это тот канал, на который вы хотите подписаться?",
                reply_markup=markup,
            )
            self.is_waiting = True
            return False

        return False

    async def callback(self, context):
        if context.callback_query.data == "subscribe_handler|confirm_channel":
            context.session_context["channel_confirmed"] = True
            await context.callback_query.edit_message_reply_markup(reply_markup=None)
            await context.callback_query.answer("Канал подтвержден")
            return True
        if context.callback_query.data == "subscribe_handler|reject_channel":
            context.session_context["channel_confirmed"] = False
            await context.callback_query.edit_message_reply_markup(reply_markup=None)
            await context.callback_query.answer("Канал отклонен")
            return True
        return False

    def stop(self):
        self.is_waiting = False


class CollectTimesStep(Step):
    def __init__(self):
        self.is_waiting = False
        self.times: list[time] = []

    async def chat(self, context):
        if not context.session_context.get("channel_confirmed", False):
            context.session_context["times"] = []
            self.is_waiting = False
            self.times = []
            return True

        if not self.is_waiting:
            await context.message.reply_text(
                _times_help_text(),
                reply_markup=_end_times_markup(),
            )
            self.is_waiting = True
            return False

        if not context.message.text:
            await context.message.reply_text(
                "Пожалуйста, введите время в одном из поддерживаемых форматов"
            )
            return False

        try:
            parsed = parse_time_input(context.message.text)
            if not parsed:
                await context.message.reply_text(
                    "Не удалось распознать время. Проверьте формат ввода."
                )
                return False

            added: list[time] = []
            already = 0
            for t in parsed:
                if t not in self.times:
                    self.times.append(t)
                    added.append(t)
                else:
                    already += 1
            self.times.sort()

            response_parts = []
            if added:
                if len(added) == 1:
                    response_parts.append(f"Добавлено время: {added[0].strftime('%H:%M')}")
                else:
                    times_str = ", ".join([t.strftime("%H:%M") for t in added])
                    response_parts.append(f"Добавлено {len(added)} времен: {times_str}")
            if already > 0:
                response_parts.append(f"{already} время(а) уже было(и) добавлено(ы)")
            await context.message.reply_text("\n".join(response_parts))
            return False
        except ValueError as e:
            await context.message.reply_text(f"Ошибка: {str(e)}")
            return False
        except Exception as e:
            logger.exception("time parse error: %s", e)
            await context.message.reply_text(
                "Произошла ошибка при обработке времени. Проверьте формат ввода."
            )
            return False

    async def callback(self, context):
        if not context.session_context.get("channel_confirmed", False):
            context.session_context["times"] = []
            self.is_waiting = False
            self.times = []
            return True

        if not self.is_waiting:
            await context.callback_query.message.chat.send_message(
                _times_help_text(),
                reply_markup=_end_times_markup(),
            )
            self.is_waiting = True
            return False

        if context.callback_query.data == "subscribe_handler|end_times":
            if len(self.times) == 0:
                await context.callback_query.message.chat.send_message(
                    "Необходимо добавить хотя бы одно время"
                )
                return False
            await context.callback_query.edit_message_reply_markup(reply_markup=None)
            await context.callback_query.answer("Ввод времени завершен")
            context.session_context["times"] = self.times
            return True
        return False

    def stop(self):
        self.is_waiting = False


def _times_help_text() -> str:
    return (
        "Введите время отправки постов. Поддерживаются следующие форматы:\n\n"
        "• Одиночное время: 12:00\n"
        "• Несколько времен через пробел: 12:00 13:00 14:00\n"
        "• Промежуток: 12:00-14:00,60\n"
        "  (начальное и конечное включительно, шаг в минутах)\n\n"
        "Примеры:\n"
        "• 09:00 12:00 18:00\n"
        "• 10:00-12:00,30 (создаст 10:00, 10:30, 11:00, 11:30, 12:00)\n"
        "• 08:00 14:00-16:00,60 20:00\n\n"
        "После ввода всех времен нажмите кнопку 'Закончить ввод'."
    )


def _end_times_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Закончить ввод",
                callback_data="subscribe_handler|end_times",
            ),
        ],
    ])

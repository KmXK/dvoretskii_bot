import logging
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import ChatBotContext
from steward.data.models.channel_subscription import ChannelSubscription
from steward.delayed_action.channel_subscription import get_posts_from_html
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.pagination import PageFormatContext, Paginator
from steward.helpers.tg_update_helpers import get_message
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step

logger = logging.getLogger(__name__)


def parse_time_input(text: str) -> list[time]:
    """
    Парсит ввод времени пользователя.
    Поддерживает:
    - Одиночное время: "12:00"
    - Несколько времен через пробел: "12:00 13:00 14:00"
    - Промежутки: "12:00-14:00,60" (начальное-конечное включительно, шаг в минутах)

    Возвращает список объектов time.
    """
    times = []
    text = text.strip()

    # Паттерн для промежутка: HH:MM-HH:MM,минуты
    interval_pattern = r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2}),(\d+)"

    # Сначала обрабатываем промежутки
    while True:
        match = re.search(interval_pattern, text)
        if not match:
            break

        start_hour = int(match.group(1))
        start_minute = int(match.group(2))
        end_hour = int(match.group(3))
        end_minute = int(match.group(4))
        step_minutes = int(match.group(5))

        if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
            raise ValueError(
                f"Неверное начальное время: {start_hour}:{start_minute:02d}"
            )
        if not (0 <= end_hour <= 23 and 0 <= end_minute <= 59):
            raise ValueError(f"Неверное конечное время: {end_hour}:{end_minute:02d}")
        if step_minutes <= 0:
            raise ValueError("Шаг должен быть положительным числом")

        start_time = time(hour=start_hour, minute=start_minute)
        end_time = time(hour=end_hour, minute=end_minute)

        # Генерируем времена в промежутке
        current = datetime.combine(datetime.today(), start_time)
        end_dt = datetime.combine(datetime.today(), end_time)

        if current > end_dt:
            raise ValueError("Начальное время должно быть меньше или равно конечному")

        interval_times = []
        while current <= end_dt:
            t = current.time()
            if t not in times and t not in interval_times:
                interval_times.append(t)
            current += timedelta(minutes=step_minutes)

        times.extend(interval_times)

        # Удаляем обработанный промежуток из текста
        text = text[: match.start()] + text[match.end() :]

    # Обрабатываем оставшиеся одиночные времена
    parts = text.split()
    for part in parts:
        part = part.strip()
        if not part:
            continue

        time_parts = part.split(":")
        if len(time_parts) != 2:
            raise ValueError(f"Неверный формат времени: {part}")

        hour = int(time_parts[0])
        minute = int(time_parts[1])

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Неверное время: {hour}:{minute:02d}")

        t = time(hour=hour, minute=minute)
        if t not in times:
            times.append(t)

    return sorted(times)


class CollectChannelPostStep(Step):
    """Шаг для получения поста из канала"""

    def __init__(self, name):
        self.name = name
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

        context.session_context[self.name] = {
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
    """Шаг для проверки канала - отправка последнего поста и подтверждение"""

    def __init__(self, name):
        self.name = name
        self.is_waiting = False
        self.last_message_sent = False
        self.confirmation_message_id: int | None = None

    async def chat(self, context):
        if not self.is_waiting:
            channel_info = context.session_context[self.name]
            channel_id = channel_info["channel_id"]
            channel_username = channel_info["channel_username"]

            if not channel_username:
                await context.message.reply_text(
                    "У канала нет username, невозможно получить посты из канала"
                )
                return True

            try:
                if channel_username:
                    channel_entity = await context.client.get_input_entity(
                        channel_username
                    )
                else:
                    channel_entity = channel_id

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
                        self.last_message_sent = True
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
            markup = InlineKeyboardMarkup(
                [
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
                ]
            )
            confirmation_msg = await context.message.reply_text(
                "Это тот канал, на который вы хотите подписаться?",
                reply_markup=markup,
            )
            self.confirmation_message_id = confirmation_msg.message_id
            self.is_waiting = True
            return False

        return False

    async def callback(self, context):
        if context.callback_query.data == "subscribe_handler|confirm_channel":
            context.session_context["channel_confirmed"] = True
            await context.callback_query.edit_message_reply_markup(reply_markup=None)
            await context.callback_query.answer("Канал подтвержден")
            return True
        elif context.callback_query.data == "subscribe_handler|reject_channel":
            context.session_context["channel_confirmed"] = False
            await context.callback_query.edit_message_reply_markup(reply_markup=None)
            await context.callback_query.answer("Канал отклонен")
            context.session_context["skip_times"] = True
            return True
        return False

    def stop(self):
        self.is_waiting = False


class CollectTimesStep(Step):
    """Шаг для сбора времени отправки постов"""

    def __init__(self, name):
        self.name = name
        self.is_waiting = False
        self.times: list[time] = []

    async def chat(self, context):
        if not context.session_context.get("channel_confirmed", False):
            context.session_context[self.name] = []
            self.is_waiting = False
            self.times = []
            return True

        if not self.is_waiting:
            help_text = (
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
            await context.message.reply_text(
                help_text,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Закончить ввод",
                                callback_data="subscribe_handler|end_times",
                            ),
                        ],
                    ]
                ),
            )
            self.is_waiting = True
            return False

        if not context.message.text:
            await context.message.reply_text(
                "Пожалуйста, введите время в одном из поддерживаемых форматов"
            )
            return False

        try:
            parsed_times = parse_time_input(context.message.text)

            if not parsed_times:
                await context.message.reply_text(
                    "Не удалось распознать время. Проверьте формат ввода."
                )
                return False

            added_times = []
            already_exists_count = 0

            for t in parsed_times:
                if t not in self.times:
                    self.times.append(t)
                    added_times.append(t)
                else:
                    already_exists_count += 1

            self.times.sort()

            response_parts = []
            if added_times:
                if len(added_times) == 1:
                    response_parts.append(
                        f"Добавлено время: {added_times[0].strftime('%H:%M')}"
                    )
                else:
                    times_str = ", ".join([t.strftime("%H:%M") for t in added_times])
                    response_parts.append(
                        f"Добавлено {len(added_times)} времен: {times_str}"
                    )

            if already_exists_count > 0:
                response_parts.append(
                    f"{already_exists_count} время(а) уже было(и) добавлено(ы)"
                )

            await context.message.reply_text("\n".join(response_parts))
            return False

        except ValueError as e:
            await context.message.reply_text(f"Ошибка: {str(e)}")
            return False
        except Exception as e:
            logger.exception(f"Error parsing time input: {e}")
            await context.message.reply_text(
                "Произошла ошибка при обработке времени. Проверьте формат ввода."
            )
            return False

    async def callback(self, context):
        if not context.session_context.get("channel_confirmed", False):
            context.session_context[self.name] = []
            self.is_waiting = False
            self.times = []
            return True

        if not self.is_waiting:
            help_text = (
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
            await context.callback_query.message.chat.send_message(
                help_text,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Закончить ввод",
                                callback_data="subscribe_handler|end_times",
                            ),
                        ],
                    ]
                ),
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
            context.session_context[self.name] = self.times
            return True
        return False

    def stop(self):
        self.is_waiting = False


class SubscribeHandler(SessionHandlerBase):
    def __init__(self):
        super().__init__(
            [
                CollectChannelPostStep("channel_info"),
                VerifyChannelStep("channel_info"),
                CollectTimesStep("times"),
            ]
        )

    def try_activate_session(self, update, session_context):
        if not validate_command_msg(update, "subscribe"):
            return False

        assert update.message and update.message.text
        parts = update.message.text.split()
        if len(parts) < 2 or parts[1] != "add":
            return False

        return True

    async def on_session_finished(self, update, session_context):
        if not session_context.get("channel_confirmed", False):
            await get_message(update).chat.send_message("Подписка отменена")
            return

        channel_info = session_context["channel_info"]
        times = session_context.get("times", [])
        chat_id = get_message(update).chat_id
        channel_id = channel_info["channel_id"]
        channel_username = channel_info["channel_username"]

        if not times:
            await get_message(update).chat.send_message(
                "Необходимо указать хотя бы одно время отправки постов"
            )
            return

        for existing_subscription in self.repository.db.channel_subscriptions:
            if (
                existing_subscription.channel_id == channel_id
                and existing_subscription.chat_id == chat_id
            ):
                await get_message(update).chat.send_message(
                    "Подписка на этот канал в этом чате уже существует"
                )
                return

        posts = await get_posts_from_html(channel_username)
        last_post_id = max(post["id"] for post in posts) if posts else 0

        max_id = (
            max(sub.id for sub in self.repository.db.channel_subscriptions)
            if self.repository.db.channel_subscriptions
            else 0
        )
        new_id = max_id + 1

        subscription = ChannelSubscription(
            id=new_id,
            channel_id=channel_id,
            channel_username=channel_username,
            chat_id=chat_id,
            times=times,
            last_post_id=last_post_id,
        )

        self.repository.db.channel_subscriptions.append(subscription)
        await self.repository.save()

        from steward.delayed_action.channel_subscription import (
            ChannelSubscriptionDelayedAction,
        )

        TIMEZONE = ZoneInfo("Europe/Minsk")
        now = datetime.now(TIMEZONE)

        for t in times:
            today = now.date()
            start = datetime.combine(today, t).replace(tzinfo=TIMEZONE)
            if start <= now:
                start = start + timedelta(days=1)

            self.repository.db.delayed_actions.append(
                ChannelSubscriptionDelayedAction(
                    subscription_id=subscription.id,
                    generator=ConstantGenerator(
                        start=start,
                        period=timedelta(days=1),
                    ),
                )
            )

        await self.repository.save()

        channel_display = channel_info.get(
            "channel_username", f"ID {channel_info['channel_id']}"
        )
        await get_message(update).chat.send_message(
            f"Подписка на канал @{channel_display} успешно создана! "
            f"ID подписки: {subscription.id}\n"
            f"Посты будут отправляться в {', '.join([t.strftime('%H:%M') for t in times])}"
        )

    async def on_stop(self, update, session_context):
        await get_message(update).chat.send_message("Подписка отменена")

    def help(self):
        return "/subscribe [add|remove <id>] - управлять подписками на каналы"

    def prompt(self):
        return (
            "▶ /subscribe — управление подписками на каналы\n"
            "  Список: /subscribe\n"
            "  Добавить: /subscribe add (начинает сессию)\n"
            "  Удалить: /subscribe remove <id>"
        )


def format_subscription_page(ctx: PageFormatContext[ChannelSubscription]) -> str:
    def format_subscription(sub: ChannelSubscription):
        times_str = ", ".join([t.strftime("%H:%M") for t in sub.times])
        channel_display = (
            f"@{sub.channel_username}"
            if sub.channel_username
            else f"ID {sub.channel_id}"
        )
        channel_display = escape_markdown(channel_display)
        return f"{channel_display} ({sub.id}) - {times_str}"

    from steward.helpers.formats import escape_markdown, format_lined_list

    return format_lined_list(
        items=[(sub.id, format_subscription(sub)) for sub in ctx.data],
        delimiter=". ",
    )


class SubscribeViewHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "subscribe"):
            return False

        assert context.message.text
        parts = context.message.text.split()
        if len(parts) > 1 and parts[1] in ["add", "remove"]:
            return False

        chat_id = context.message.chat_id
        subscriptions = [
            s for s in self.repository.db.channel_subscriptions if s.chat_id == chat_id
        ]

        if not subscriptions:
            await context.message.reply_text("В этом чате нет подписок на каналы")
            return True

        return await self._get_paginator(chat_id).show_list(context.update)

    async def callback(self, context: ChatBotContext):
        assert context.callback_query and context.callback_query.data

        from steward.helpers.keyboard import parse_and_validate_keyboard
        from steward.helpers.pagination import parse_pagination

        pagination_parsed = parse_and_validate_keyboard(
            "subscription_list",
            context.callback_query.data,
            parse_func=parse_pagination,
        )

        if pagination_parsed is not None:
            chat_id = context.callback_query.message.chat.id
            return await self._get_paginator(chat_id).process_parsed_callback(
                context.update,
                pagination_parsed,
            )

        return False

    def _get_paginator(self, chat_id: int) -> Paginator:
        paginator = Paginator(
            unique_keyboard_name="subscription_list",
            list_header="Подписки на каналы",
            page_size=15,
            page_format_func=format_subscription_page,
            always_show_pagination=True,
        )

        paginator.data_func = lambda: [
            s for s in self.repository.db.channel_subscriptions if s.chat_id == chat_id
        ]

        return paginator

    def help(self):
        return None


class SubscribeRemoveHandler(Handler):
    async def chat(self, context: ChatBotContext):
        if not validate_command_msg(context.update, "subscribe"):
            return False

        assert context.message.text
        parts = context.message.text.split()
        if len(parts) < 3 or parts[1] != "remove":
            return False

        try:
            subscription_id = int(parts[2])
        except ValueError:
            await context.message.reply_text("Неверный ID подписки")
            return True

        chat_id = context.message.chat_id
        subscription = next(
            (
                s
                for s in self.repository.db.channel_subscriptions
                if s.id == subscription_id and s.chat_id == chat_id
            ),
            None,
        )

        if subscription is None:
            await context.message.reply_text(
                "Подписка с таким ID не найдена в этом чате"
            )
            return True

        self.repository.db.channel_subscriptions.remove(subscription)

        from steward.delayed_action.channel_subscription import (
            ChannelSubscriptionDelayedAction,
        )

        actions_to_remove = [
            action
            for action in self.repository.db.delayed_actions
            if isinstance(action, ChannelSubscriptionDelayedAction)
            and action.subscription_id == subscription_id
        ]

        for action in actions_to_remove:
            self.repository.db.delayed_actions.remove(action)

        await self.repository.save()

        channel_display = (
            f"@{subscription.channel_username}"
            if subscription.channel_username
            else f"ID {subscription.channel_id}"
        )
        await context.message.reply_text(
            f"Подписка на канал {channel_display} (ID: {subscription_id}) удалена"
        )
        return True

    def help(self):
        return None

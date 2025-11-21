import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.bot.context import ChatBotContext
from steward.data.models.channel_subscription import ChannelSubscription
from steward.delayed_action.channel_subscription import get_posts_from_rss
from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg
from steward.helpers.pagination import PageFormatContext, Paginator
from steward.helpers.tg_update_helpers import get_message
from steward.helpers.validation import (
    check,
    try_get,
    validate_message_text,
    validate_update,
)
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.step import Step
from steward.session.steps.keyboard_step import KeyboardStep
from steward.session.steps.question_step import QuestionStep

logger = logging.getLogger(__name__)


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

        # Проверяем, что сообщение переслано
        if not context.message.forward_origin:
            await context.message.reply_text(
                "Это сообщение не переслано из канала. Пожалуйста, перешлите пост из канала."
            )
            return False

        # Проверяем, что это пересылка из чата (канала)
        if not hasattr(context.message.forward_origin, "chat"):
            await context.message.reply_text(
                "Это сообщение не переслано из канала. Пожалуйста, перешлите пост из канала."
            )
            return False

        forward_chat = context.message.forward_origin.chat

        # Проверяем, что это канал
        if forward_chat.type != "channel":
            await context.message.reply_text(
                "Это не канал. Пожалуйста, перешлите пост из канала."
            )
            return False

        # Сохраняем информацию о канале
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
                    "У канала нет username, невозможно получить RSS фид"
                )
                return True  # Пропускаем этот шаг

            try:
                # Получаем посты из RSS
                posts = await get_posts_from_rss(channel_username)
                if posts:
                    # Берем последний пост (с максимальным ID)
                    last_post = posts[-1]
                    # Получаем сообщение по ID
                    message = await context.client.get_messages(
                        channel_id, ids=last_post["id"]
                    )
                    if message:
                        # Пересылаем последнее сообщение
                        await context.message.chat.send_message(
                            "Это последнее сообщение из канала:"
                        )
                        await context.client.forward_messages(
                            context.message.chat_id,
                            message,
                            from_peer=channel_id,
                        )
                        self.last_message_sent = True
                else:
                    await context.message.reply_text(
                        "Не удалось получить последнее сообщение из RSS фида канала"
                    )
                    return True  # Пропускаем этот шаг
            except Exception as e:
                logger.exception(e)
                await context.message.reply_text(
                    f"Ошибка при получении последнего сообщения: {str(e)}"
                )
                return True  # Пропускаем этот шаг

            # Спрашиваем подтверждение
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
            # Убираем кнопки из сообщения
            await context.callback_query.edit_message_reply_markup(reply_markup=None)
            await context.callback_query.answer("Канал подтвержден")
            return True
        elif context.callback_query.data == "subscribe_handler|reject_channel":
            context.session_context["channel_confirmed"] = False
            # Убираем кнопки из сообщения
            await context.callback_query.edit_message_reply_markup(reply_markup=None)
            await context.callback_query.answer("Канал отклонен")
            # Пропускаем остальные шаги, завершаем сессию
            # Это обработается в on_session_finished
            # Устанавливаем флаг, чтобы пропустить CollectTimesStep
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
        # Проверяем, подтвержден ли канал
        if not context.session_context.get("channel_confirmed", False):
            # Канал не подтвержден, пропускаем этот шаг
            context.session_context[self.name] = []
            return True

        if not self.is_waiting:
            await context.message.reply_text(
                "Введите время отправки постов в формате HH:MM (можно несколько раз, каждое время отдельным сообщением). После ввода всех времен нажмите кнопку 'Закончить ввод'.",
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

        # Парсим время
        if not context.message.text:
            await context.message.reply_text(
                "Пожалуйста, введите время в формате HH:MM"
            )
            return False

        try:
            parts = context.message.text.split(":")
            if len(parts) != 2:
                await context.message.reply_text(
                    "Неверный формат времени. Используйте формат HH:MM (например, 16:00)"
                )
                return False

            hour = int(parts[0])
            minute = int(parts[1])

            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                await context.message.reply_text(
                    "Неверное время. Часы должны быть от 0 до 23, минуты от 0 до 59"
                )
                return False

            t = time(hour=hour, minute=minute)
            if t not in self.times:
                self.times.append(t)
                await context.message.reply_text(
                    f"Время {t.strftime('%H:%M')} добавлено"
                )
            else:
                await context.message.reply_text("Это время уже добавлено")
            return False

        except (ValueError, IndexError):
            await context.message.reply_text(
                "Неверный формат времени. Используйте формат HH:MM (например, 16:00)"
            )
            return False

    async def callback(self, context):
        if not self.is_waiting:
            # Если шаг только начался (например, после callback из предыдущего шага),
            # отправляем сообщение с просьбой ввести время
            await context.callback_query.message.chat.send_message(
                "Введите время отправки постов в формате HH:MM (можно несколько раз, каждое время отдельным сообщением). После ввода всех времен нажмите кнопку 'Закончить ввод'.",
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
            # Убираем кнопки из сообщения
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
        # Активируем сессию только если команда /subscribe без дополнительных аргументов
        if not validate_command_msg(update, "subscribe"):
            return False

        # Проверяем, что нет подкоманд
        assert update.message and update.message.text
        parts = update.message.text.split()
        if len(parts) > 1 and parts[1] in ["view", "remove"]:
            return False  # Это обработают другие обработчики

        return True

    async def on_session_finished(self, update, session_context):
        # Проверяем, был ли канал подтвержден
        if not session_context.get("channel_confirmed", False):
            await get_message(update).chat.send_message("Подписка отменена")
            return

        channel_info = session_context["channel_info"]
        times = session_context.get("times", [])
        chat_id = get_message(update).chat_id
        channel_id = channel_info["channel_id"]
        channel_username = channel_info["channel_username"]

        # Проверяем, что введено хотя бы одно время
        if not times or len(times) == 0:
            await get_message(update).chat.send_message(
                "Необходимо указать хотя бы одно время отправки постов"
            )
            return

        # Проверяем, нет ли уже подписки на этот канал в этом чате
        for existing_subscription in self.repository.db.channel_subscriptions:
            if (
                existing_subscription.channel_id == channel_id
                and existing_subscription.chat_id == chat_id
            ):
                await get_message(update).chat.send_message(
                    "Подписка на этот канал в этом чате уже существует"
                )
                return

        # Получаем текущие посты из RSS, чтобы установить last_post_id
        posts = await get_posts_from_rss(channel_username)
        last_post_id = 0
        if posts:
            # Устанавливаем last_post_id на максимальный ID из текущих постов
            last_post_id = max(post["id"] for post in posts)

        # Генерируем ID для новой подписки: максимальный из всех существующих + 1
        max_id = 0
        if self.repository.db.channel_subscriptions:
            max_id = max(sub.id for sub in self.repository.db.channel_subscriptions)
        new_id = max_id + 1

        # Создаем подписку
        subscription = ChannelSubscription(
            id=new_id,
            channel_id=channel_id,
            channel_username=channel_username,
            chat_id=chat_id,
            times=times,
            last_post_id=last_post_id,  # Устанавливаем на последний пост из канала
        )

        self.repository.db.channel_subscriptions.append(subscription)
        await self.repository.save()

        # Создаем отложенные действия для каждого времени
        from steward.delayed_action.channel_subscription import (
            ChannelSubscriptionDelayedAction,
        )
        from steward.delayed_action.generators.channel_subscription_generator import (
            ChannelSubscriptionGenerator,
        )

        TIMEZONE = ZoneInfo("Europe/Minsk")
        now = datetime.now(TIMEZONE)

        for t in times:
            # Вычисляем start время для генератора
            today = now.date()
            start = datetime.combine(today, t).replace(tzinfo=TIMEZONE)
            # Если время уже прошло сегодня, планируем на завтра
            if start <= now:
                start = start + timedelta(days=1)

            generator = ChannelSubscriptionGenerator(
                subscription_id=subscription.id,  # Используем ID подписки
                target_time=t,
                start=start,
            )
            delayed_action = ChannelSubscriptionDelayedAction(
                subscription_id=subscription.id,  # Используем ID подписки
                generator=generator,
            )
            self.repository.db.delayed_actions.append(delayed_action)

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
        return (
            "/subscribe - подписаться на канал\n"
            "/subscribe view - посмотреть все подписки в этом чате\n"
            "/subscribe remove <id> - удалить подписку по ID"
        )


def format_subscription_page(ctx: PageFormatContext[ChannelSubscription]) -> str:
    def format_subscription(sub: ChannelSubscription):
        times_str = ", ".join([t.strftime("%H:%M") for t in sub.times])
        channel_display = (
            f"@{sub.channel_username}"
            if sub.channel_username
            else f"ID {sub.channel_id}"
        )
        return f"{channel_display} ({sub.id}) - {times_str}"

    from steward.helpers.formats import format_lined_list

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
        if len(parts) < 2 or parts[1] != "view":
            return False

        chat_id = context.message.chat_id

        # Получаем все подписки для этого чата
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


class SubscribeRemoveHandler(Handler):
    async def chat(self, context: ChatBotContext):
        # Парсим команду вручную
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

        # Ищем подписку по ID и проверяем, что она принадлежит этому чату
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

        # Удаляем подписку
        self.repository.db.channel_subscriptions.remove(subscription)

        # Удаляем все связанные отложенные действия
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

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from aiohttp import ClientSession

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark

CHANNEL_ID = -1002200475386
RSS_URL = "https://tg.i-c-a.su/rss/smartfeetbaby"


async def get_last_post_id_from_rss() -> int | None:
    """Получает ID последнего поста из RSS фида"""
    try:
        async with ClientSession() as session:
            async with session.get(RSS_URL) as response:
                if response.status != 200:
                    return None

                content = await response.text()
                root = ET.fromstring(content)

                # Находим первый item (последний пост)
                item = root.find(".//item")
                if item is None:
                    return None

                # Получаем link
                link_elem = item.find("link")
                if link_elem is None or link_elem.text is None:
                    return None

                # Извлекаем ID из URL (последнее число после слеша)
                # Например: https://t.me/smartfeetbaby/491 -> 491
                link = link_elem.text
                path = urlparse(link).path
                message_id = path.rstrip("/").split("/")[-1]

                return int(message_id)
    except Exception:
        return None


@dataclass
@class_mark("generator/single_time")
class SingleTimeGenerator(Generator):
    """Генератор для одноразового выполнения в указанное время"""

    target_time: datetime

    def get_next(self, now: datetime) -> datetime | None:
        if self.target_time >= now:
            return self.target_time
        return None  # Время уже прошло


@dataclass
@class_mark("delayed_action/post")
class PostDelayedAction(DelayedAction):
    """Отложенная отправка поста из канала"""

    chat_id: int
    channel_id: int
    generator: SingleTimeGenerator

    async def execute(self, context: DelayedActionContext):
        """Выполняет получение и пересылку последнего поста из канала"""
        try:
            # Получаем ID последнего поста из RSS
            message_id = await get_last_post_id_from_rss()

            if message_id is None:
                await context.bot.send_message(
                    self.chat_id, "Не удалось получить ID последнего поста из RSS"
                )
                return

            # Получаем сообщение по ID
            message = await context.client.get_messages(self.channel_id, ids=message_id)
            print(message.peer_id.channel_id - 1000000000000)

        except Exception as e:
            # В случае ошибки отправляем текстовое сообщение
            try:
                await context.bot.send_message(
                    self.chat_id, f"Ошибка при пересылке поста: {str(e)}"
                )
            except Exception:
                pass  # Игнорируем ошибку отправки

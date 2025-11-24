import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse

from aiohttp import ClientSession

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.helpers.class_mark import class_mark

logger = logging.getLogger(__name__)

RSS_BASE_URL = "https://tg.i-c-a.su/rss"


async def get_posts_from_rss(channel_username: str) -> list[dict[str, int]]:
    """Получает список постов из RSS фида с их ID"""
    rss_url = f"{RSS_BASE_URL}/{channel_username}"
    posts = []

    try:
        async with ClientSession() as session:
            async with session.get(rss_url) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch RSS: {response.status}")
                    return posts

                content = await response.text()
                root = ET.fromstring(content)

                for item in root.findall(".//item"):
                    link_elem = item.find("link")
                    if link_elem is None or link_elem.text is None:
                        continue

                    # Извлекаем ID из URL (последнее число после слеша)
                    # Например: https://t.me/smartfeetbaby/491 -> 491
                    link = link_elem.text
                    path = urlparse(link).path
                    try:
                        message_id = int(path.rstrip("/").split("/")[-1])
                        posts.append({"id": message_id, "link": link})
                    except (ValueError, IndexError):
                        continue

                posts.sort(key=lambda x: x["id"])
    except Exception as e:
        logger.exception(f"Error fetching RSS feed: {e}")

    return posts


@dataclass(kw_only=True)
@class_mark("delayed_action/channel_subscription")
class ChannelSubscriptionDelayedAction(DelayedAction):
    subscription_id: int

    generator: ConstantGenerator

    async def execute(self, context: DelayedActionContext):
        """Выполняет получение и пересылку новых постов из канала"""
        try:
            subscription = next(
                (
                    s
                    for s in context.repository.db.channel_subscriptions
                    if s.id == self.subscription_id
                ),
                None,
            )
            if subscription is None:
                logger.error(
                    f"Subscription with id {self.subscription_id} not found in database"
                )
                return

            posts = await get_posts_from_rss(subscription.channel_username)

            if not posts:
                logger.warning(
                    f"No posts found in RSS for channel {subscription.channel_username}"
                )
                return

            new_posts = [
                post for post in posts if post["id"] > subscription.last_post_id
            ]

            if not new_posts:
                return

            for post in new_posts:
                try:
                    message = await context.client.get_messages(
                        subscription.channel_id, ids=post["id"]
                    )
                    if message:
                        await context.client.forward_messages(
                            subscription.chat_id,
                            message,
                            from_peer=subscription.channel_id,
                        )
                except Exception as e:
                    logger.exception(
                        f"Error forwarding message {post['id']} from channel {subscription.channel_id}: {e}"
                    )

            if new_posts:
                subscription.last_post_id = max(post["id"] for post in new_posts)
                await context.repository.save()

        except IndexError:
            logger.error(
                f"Subscription with id {self.subscription_id} not found in database"
            )
        except Exception as e:
            logger.exception(f"Error executing channel subscription action: {e}")

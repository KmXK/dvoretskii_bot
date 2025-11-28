import logging
import os
from dataclasses import dataclass

from aiohttp import ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup

from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.constant_generator import ConstantGenerator
from steward.helpers.class_mark import class_mark

logger = logging.getLogger(__name__)

TELEGRAM_CHANNEL_URL = "https://t.me/s"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def get_posts_from_html(channel_username: str) -> list[dict[str, int]]:
    """Получает список постов из HTML страницы Telegram канала с их ID"""
    channel_url = f"{TELEGRAM_CHANNEL_URL}/{channel_username}"
    posts = []

    try:
        connector = None
        proxy_url = os.environ.get("DOWNLOAD_PROXY")
        if proxy_url:
            connector = ProxyConnector.from_url(proxy_url)

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        timeout = ClientTimeout(total=30, connect=10)

        async with ClientSession(
            connector=connector, timeout=timeout, headers=headers
        ) as session:
            async with session.get(channel_url) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch HTML: {response.status}")
                    return posts

                content = await response.text()
                soup = BeautifulSoup(content, "html.parser")

                messages = soup.find_all("div", class_="tgme_widget_message")

                for message in messages:
                    data_post = message.get("data-post", "")
                    if not data_post:
                        continue

                    try:
                        parts = data_post.split("/")
                        if len(parts) >= 2:
                            message_id = int(parts[-1])
                            link = f"https://t.me/{data_post}"
                            posts.append({"id": message_id, "link": link})
                    except (ValueError, IndexError):
                        continue

                posts.sort(key=lambda x: x["id"])
    except Exception as e:
        logger.exception(f"Error fetching HTML page: {e}")

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

            posts = await get_posts_from_html(subscription.channel_username)

            if not posts:
                logger.warning(
                    f"No posts found in HTML for channel {subscription.channel_username}"
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

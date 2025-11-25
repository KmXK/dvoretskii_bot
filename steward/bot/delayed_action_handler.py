import asyncio
import logging
from datetime import datetime, timedelta, timezone
from inspect import isawaitable

from telegram.ext import ExtBot
from telethon import TelegramClient

from steward.data.repository import Repository
from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext

logger = logging.getLogger(__name__)


default_actions: list[DelayedAction] = []


class DelayedActionHandler:
    def __init__(
        self, repository: Repository, bot: ExtBot[None], client: TelegramClient
    ):
        self._repository = repository
        self._bot = bot
        self._client = client
        self._update_future: asyncio.Future[None] = asyncio.Future()
        self._repository.subscribe_on_save(lambda: self._update_future.set_result(None))

    async def start(self):
        context = DelayedActionContext(self._repository, self._bot, self._client)

        while True:
            logger.info("Checking delayed actions...")
            nearest_time, actions = await self._get_nearest_actions()
            logger.info(
                f"Nearest actions count: {len(actions)}. Time to execute: {nearest_time.isoformat()}"
            )

            done, _ = await asyncio.wait(
                [
                    asyncio.create_task(
                        asyncio.sleep(
                            (nearest_time - datetime.now(timezone.utc)).total_seconds()
                        )
                    ),
                    self._update_future,
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )

            logger.info("Waiting ended")

            if self._update_future in done:
                logger.info("Waiting ended due to update")
                self._update_future = asyncio.Future()
                continue

            ms = (datetime.now(timezone.utc) - nearest_time).microseconds
            if ms >= 30e3:
                logger.warning(f"Skipped action due to long waiting: {ms} microseconds")
                continue

            # waited -> execute actions
            for action in actions:
                logger.info(f"Executing action: {action}")
                await action.execute(context)

    async def _get_nearest_actions(self) -> tuple[datetime, list[DelayedAction]]:
        nearest_delayed_actions: list[DelayedAction] = []
        min_waiting_time = datetime.max.replace(tzinfo=timezone.utc) - timedelta(days=1)

        now = datetime.now(timezone.utc)

        has_deleted = False

        for action in self._repository.db.delayed_actions:
            nearest_time = action.generator.get_next(now)
            if isawaitable(nearest_time):
                nearest_time = await nearest_time

            if nearest_time is None:
                logging.debug(f"Delayed action is removed {action}")
                self._repository.db.delayed_actions.remove(action)
                has_deleted = True
                continue

            if nearest_time.tzinfo is None:
                nearest_time = nearest_time.replace(tzinfo=timezone.utc)

            if min_waiting_time == nearest_time:
                nearest_delayed_actions.append(action)
            elif min_waiting_time > nearest_time:
                nearest_delayed_actions = [action]
                min_waiting_time = nearest_time

        if has_deleted:
            await self._repository.save()

        return min_waiting_time, nearest_delayed_actions

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from steward.data.models.reward import Reward
from steward.data.repository import Repository
from steward.metrics.base import MetricsEngine

logger = logging.getLogger(__name__)

RECALC_INTERVAL_SECONDS = 3600
PROMQL_RANGE = "540d"


@dataclass
class DynamicRewardDef:
    key: str
    name: str
    emoji: str
    description: str


DYNAMIC_REWARD_DEFS: list[DynamicRewardDef] = [
    DynamicRewardDef(
        key="most_messages",
        name="Болтун",
        emoji="💬",
        description="Больше всего сообщений",
    ),
    DynamicRewardDef(
        key="most_poker_hands",
        name="Картёжник",
        emoji="🃏",
        description="Больше всего покерных раздач",
    ),
    DynamicRewardDef(
        key="best_poker_winrate",
        name="Шулер",
        emoji="🎯",
        description="Лучший винрейт в покере (мин. 10 раздач)",
    ),
    DynamicRewardDef(
        key="most_monkeys",
        name="Обезьяний рабовладелец",
        emoji="🐵",
        description="Больше всего обезьянок",
    ),
    DynamicRewardDef(
        key="most_casino_games",
        name="Главный лудик",
        emoji="🎲",
        description="Больше всего игр в казино",
    ),
    DynamicRewardDef(
        key="most_casino_bet",
        name="Спонсор",
        emoji="💸",
        description="Больше всего поставлено обезьянок",
    ),
]


def _top1_promql(metric: str, **filters) -> str:
    label_filter = ", ".join(f'{k}="{v}"' for k, v in filters.items())
    return f"topk(1, sum by (user_id, user_name) (increase({metric}{{{label_filter}}}[{PROMQL_RANGE}])))"


async def _resolve_metric_top(
    metrics: MetricsEngine, metric: str, **filters
) -> Optional[int]:
    promql = _top1_promql(metric, **filters)
    samples = await metrics.query(promql)
    if not samples:
        return None
    best = max(samples, key=lambda s: s.value)
    if best.value <= 0:
        return None
    uid = best.labels.get("user_id")
    if not uid:
        return None
    try:
        return int(uid)
    except ValueError:
        return None


async def _resolve_poker_winrate(
    metrics: MetricsEngine, repository: Repository
) -> Optional[int]:
    r = PROMQL_RANGE
    wins_q = f'sum by (user_id) (increase(poker_hands_total{{result="win"}}[{r}]))'
    total_q = f"sum by (user_id) (increase(poker_hands_total[{r}]))"
    wins_samples = await metrics.query(wins_q)
    total_samples = await metrics.query(total_q)

    total_map: dict[str, float] = {}
    for s in total_samples:
        uid = s.labels.get("user_id", "")
        if uid:
            total_map[uid] = s.value

    wins_map: dict[str, float] = {}
    for s in wins_samples:
        uid = s.labels.get("user_id", "")
        if uid:
            wins_map[uid] = s.value

    best_uid: Optional[str] = None
    best_rate = -1.0
    min_hands = 10

    for uid, total in total_map.items():
        if total < min_hands:
            continue
        wins = wins_map.get(uid, 0)
        rate = wins / total
        if rate > best_rate:
            best_rate = rate
            best_uid = uid

    if best_uid is None:
        return None
    try:
        return int(best_uid)
    except ValueError:
        return None


async def _resolve_most_monkeys(repository: Repository) -> Optional[int]:
    users = repository.db.users
    if not users:
        return None
    best = max(users, key=lambda u: u.monkeys)
    if best.monkeys <= 0:
        return None
    return best.id


RESOLVERS: dict[str, Callable] = {
    "most_messages": lambda m, r: _resolve_metric_top(
        m, "bot_messages_total", action_type="chat"
    ),
    "most_poker_hands": lambda m, r: _resolve_metric_top(m, "poker_hands_total"),
    "best_poker_winrate": lambda m, r: _resolve_poker_winrate(m, r),
    "most_monkeys": lambda m, r: _resolve_most_monkeys(r),
    "most_casino_games": lambda m, r: _resolve_metric_top(m, "casino_games_total"),
    "most_casino_bet": lambda m, r: _resolve_metric_top(m, "casino_monkeys_bet_total"),
}


def ensure_dynamic_rewards_exist(repository: Repository) -> bool:
    existing_keys = {r.dynamic_key for r in repository.db.rewards if r.dynamic_key}
    changed = False
    for d in DYNAMIC_REWARD_DEFS:
        if d.key not in existing_keys:
            max_id = max((r.id for r in repository.db.rewards), default=0)
            reward = Reward(
                id=max_id + 1,
                name=d.name,
                emoji=d.emoji,
                description=d.description,
                dynamic_key=d.key,
            )
            repository.db.rewards.append(reward)
            changed = True
            logger.info("Created dynamic reward: %s (id=%d)", d.key, reward.id)
    return changed


def get_dynamic_reward_holder(repository: Repository, reward: Reward) -> Optional[int]:
    if not reward.dynamic_key:
        return None
    user = next(
        (u for u in repository.db.users if reward.id in u.reward_ids),
        None,
    )
    return user.id if user else None


def get_holder_display_name(repository: Repository, user_id: int) -> str:
    user = next((u for u in repository.db.users if u.id == user_id), None)
    if user and user.username:
        return f"@{user.username}"
    return str(user_id)


class DynamicRewardChecker:
    def __init__(self, repository: Repository, metrics: MetricsEngine):
        self._repository = repository
        self._metrics = metrics

    async def start(self):
        await asyncio.sleep(10)
        while True:
            try:
                await self._recalculate()
            except Exception:
                logger.exception("Dynamic reward recalculation failed")
            await asyncio.sleep(RECALC_INTERVAL_SECONDS)

    async def _recalculate(self):
        logger.info("Recalculating dynamic rewards...")
        db = self._repository.db
        changed = False

        for reward in db.rewards:
            if not reward.dynamic_key:
                continue
            resolver = RESOLVERS.get(reward.dynamic_key)
            if not resolver:
                continue

            new_holder_id = await resolver(self._metrics, self._repository)

            current_holder = next(
                (u for u in db.users if reward.id in u.reward_ids),
                None,
            )
            current_holder_id = current_holder.id if current_holder else None

            if new_holder_id == current_holder_id:
                continue

            if current_holder is not None:
                current_holder.reward_ids.remove(reward.id)
                changed = True

            if new_holder_id is not None:
                new_holder = next((u for u in db.users if u.id == new_holder_id), None)
                if new_holder is not None:
                    new_holder.reward_ids.append(reward.id)
                    changed = True
                    logger.info(
                        "Dynamic reward '%s' transferred to user %d",
                        reward.name,
                        new_holder_id,
                    )

        if changed:
            await self._repository.save()
        logger.info("Dynamic rewards recalculation complete")

from dataclasses import dataclass
from typing import Optional


@dataclass
class Reward:
    id: int
    name: str
    emoji: str
    description: str = ""
    custom_emoji_id: Optional[str] = None


@dataclass
class UserReward:
    user_id: int
    reward_id: int

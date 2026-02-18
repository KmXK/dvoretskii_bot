import logging
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Sized

from dacite import Config, from_dict

from steward.data.models.ai_message import AiMessage
from steward.data.models.saved_links import SavedLinks
from steward.delayed_action.base import DelayedAction
from steward.delayed_action.reminder import CompletedReminder
from steward.helpers.class_mark import try_get_class_by_mark

from .army import Army
from .banned_user import BannedUser
from .birthday import Birthday
from .bill import Bill, DetailsInfo, Payment
from .channel_subscription import ChannelSubscription
from .chat import Chat
from .feature_request import FeatureRequest
from .reward import Reward, UserReward
from .rule import Rule
from .todo_item import TodoItem
from .user import User
from .video_reaction import VideoReaction


@dataclass
class Database:
    admin_ids: set[int] = field(default_factory=set)
    ai_messages: dict[str, AiMessage] = field(default_factory=dict)
    army: list[Army] = field(default_factory=list)
    chats: list[Chat] = field(default_factory=list)
    silenced_chats: dict[int, datetime] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    feature_requests: list[FeatureRequest] = field(default_factory=list)
    delayed_actions: list[DelayedAction] = field(default_factory=list)
    completed_reminders: list[CompletedReminder] = field(default_factory=list)
    saved_links: SavedLinks = field(default_factory=SavedLinks)
    data_offsets: dict[str, float] = field(default_factory=dict)
    channel_subscriptions: list[ChannelSubscription] = field(default_factory=list)
    bills: list[Bill] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    details_infos: list[DetailsInfo] = field(default_factory=list)
    users: list[User] = field(default_factory=list)
    rewards: list[Reward] = field(default_factory=list)
    user_rewards: list[UserReward] = field(default_factory=list)
    todo_items: list[TodoItem] = field(default_factory=list)
    banned_users: list[BannedUser] = field(default_factory=list)
    birthdays: list[Birthday] = field(default_factory=list)
    video_reactions: list[VideoReaction] = field(default_factory=list)

    version: int = 9


PARSE_CONFIG = Config(
    cast=[
        Enum,
        set,
    ],
    type_hooks={
        datetime: lambda s: datetime.fromisoformat(s)
        if isinstance(s, str)
        else datetime.fromtimestamp(s, tz=timezone.utc),
        timedelta: lambda s: timedelta(seconds=s),
        time: lambda s: time.fromisoformat(s)
        if isinstance(s, str)
        else time(hour=s // 3600, minute=(s % 3600) // 60, second=s % 60),
    },
)


def populate_object_with_marked_fields(real_obj: Any, dict_obj: dict[Any, Any]):
    def create_marked_field(field_data: Any):
        def iter_wrap[T: Sized](default: T, add_func: Callable[[T, Any], None]):
            value = default
            for item in field_data:
                x = create_marked_field(item)
                if x is not None:
                    add_func(value, x)
            return value if len(value) > 0 else None

        if isinstance(field_data, list):
            return iter_wrap(list(), lambda l, v: l.append(v))
        elif isinstance(field_data, set):
            return iter_wrap(set(), lambda s, v: s.add(v))

        if not isinstance(field_data, dict):
            return None

        cls = try_get_class_by_mark(field_data)

        if not cls:
            return None

        try:
            value = from_dict(
                data_class=cls,
                data=field_data,
                config=PARSE_CONFIG,
            )

            populate_object_with_marked_fields(
                value,
                field_data,
            )
        except BaseException as e:
            logging.exception(e)
            return None

        return value

    if not is_dataclass(real_obj):
        return {}

    for f in real_obj.__dataclass_fields__.values():
        value = create_marked_field(dict_obj.get(f.name))
        if value is not None:
            setattr(real_obj, f.name, value)


def parse_from_dict(data: dict[str, Any]) -> Database:
    db = from_dict(
        data_class=Database,
        data=data,
        config=PARSE_CONFIG,
    )

    populate_object_with_marked_fields(db, data)
    return db


def serialize_to_dict(db: Database) -> dict[str, Any]:
    return asdict(db)

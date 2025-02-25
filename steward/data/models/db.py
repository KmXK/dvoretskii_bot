import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from dacite import Config, from_dict

from steward.delayed_action.base import DelayedAction
from steward.helpers.class_mark import get_class_by_mark

from .army import Army
from .chat import Chat
from .feature_request import FeatureRequest
from .rule import Rule


@dataclass
class Database:
    admin_ids: set[int] = field(default_factory=set)
    army: list[Army] = field(default_factory=list)
    chats: list[Chat] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    feature_requests: list[FeatureRequest] = field(default_factory=list)
    delayed_actions: list[DelayedAction] = field(default_factory=list)
    version: int = 3


def parse_from_dict(data: dict[str, Any]) -> Database:
    config = Config(
        cast=[Enum],
        type_hooks={
            datetime: lambda s: datetime.fromtimestamp(s),
            timedelta: lambda s: timedelta(seconds=s),
        },
    )

    db = from_dict(
        data_class=Database,
        data=data,
        config=config,
    )

    db.delayed_actions.clear()

    # custom logic for delayed actions because we use __class_mark__ as hint
    # to choose concrete class for the value
    for action in data.get("delayed_actions", []):
        try:
            generator = from_dict(
                data_class=get_class_by_mark(
                    "generator",
                    action["generator"],
                ),
                data=action["generator"],
                config=config,
            )

            real_action = from_dict(
                data_class=get_class_by_mark("delayed_action", action),
                data=action,
                config=config,
            )

            real_action.generator = generator

            db.delayed_actions.append(real_action)
        except BaseException as e:
            logging.exception(e)
            continue

    return db


def serialize_to_dict(db: Database) -> dict[str, Any]:
    return asdict(db)

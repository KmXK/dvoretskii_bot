import logging
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Sized

from dacite import Config, from_dict

from steward.data.models.pasha_ai_message import PashaAiMessage
from steward.data.models.saved_links import SavedLinks
from steward.delayed_action.base import DelayedAction
from steward.helpers.class_mark import try_get_class_by_mark

from .army import Army
from .chat import Chat
from .feature_request import FeatureRequest
from .rule import Rule


@dataclass
class Database:
    admin_ids: set[int] = field(default_factory=set)
    pasha_ai_messages: dict[str, PashaAiMessage] = field(default_factory=dict)
    army: list[Army] = field(default_factory=list)
    chats: list[Chat] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    feature_requests: list[FeatureRequest] = field(default_factory=list)
    delayed_actions: list[DelayedAction] = field(default_factory=list)
    saved_links: SavedLinks = field(default_factory=SavedLinks)

    version: int = 3


PARSE_CONFIG = Config(
    cast=[
        Enum,
        set,
    ],
    type_hooks={
        datetime: lambda s: datetime.fromtimestamp(s, tz=timezone.utc),
        timedelta: lambda s: timedelta(seconds=s),
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

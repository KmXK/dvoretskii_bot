from steward.features.admin import AdminFeature
from steward.features.ai import AIFeature
from steward.features.alias import AliasFeature
# SettingsFeature imported lazily inside helpers to avoid cycles
from steward.features.ai_related import AiRelatedFeature
from steward.features.army import ArmyFeature
from steward.features.ban import BanEnforcerFeature, BanFeature
from steward.features.bills import BillsFeature
from steward.features.birthday import BirthdayFeature
from steward.features.broadcast import BroadcastFeature
from steward.features.chat_collect import ChatCollectFeature
from steward.features.curse import CurseFeature
from steward.features.curse_metric import CurseMetricFeature
from steward.features.db import DbFeature
from steward.features.diana import DianaFeature
from steward.features.download import DownloadFeature
from steward.features.everyone import EveryoneFeature
from steward.features.exchange_rates import ExchangeRateFeature
from steward.features.feature_request import FeatureRequestFeature
from steward.features.fuck import FuckFeature, SexFeature
from steward.features.google_drive import GoogleDriveFeature
from steward.features.highcast_cleanup import HighcastCleanupFeature
from steward.features.holidays import HolidaysFeature
from steward.features.joke import JokeFeature
from steward.features.id import IdFeature
from steward.features.incident import IncidentFeature
from steward.features.lang import LangFeature
from steward.features.layout import LayoutFeature
from steward.features.link import LinkFeature
from steward.features.me import MeFeature
from steward.features.message_info import MessageInfoFeature
from steward.features.miniapp import MiniAppFeature
from steward.features.multiply import MultiplyFeature
from steward.features.news_video import NewsVideoFeature
from steward.features.newtext import NewTextFeature
from steward.features.pasha import PashaFeature
from steward.features.pretty_time import PrettyTimeFeature
from steward.features.react import ReactFeature
from steward.features.reaction_counter import ReactionCounterFeature
from steward.features.remind import RemindersFeature, RemindFeature
from steward.features.reward import RewardFeature
from steward.features.rule import RuleFeature
from steward.features.rule_answer import RuleAnswerFeature
from steward.features.silence import SilenceEnforcerFeature, SilenceFeature
from steward.features.stands import StandsFeature
from steward.features.stats import StatsFeature
from steward.features.subscribe import SubscribeFeature
from steward.features.tarot import TarotFeature
from steward.features.tennis import TennisFeature
from steward.features.timezone import TimezoneFeature
from steward.features.todo import TodoFeature
from steward.features.settings import SettingsFeature
from steward.features.shazam import ShazamFeature
from steward.features.transcribe import TranscribeFeature
from steward.features.translate import TranslateFeature
from steward.features.tts import TtsTestFeature
from steward.features.tunnel import TunnelFeature
from steward.features.user_memory import UserMemoryFeature
from steward.features.voice_video import VoiceVideoFeature
from steward.features.watch import WatchFeature
from steward.framework import bucket
from steward.handlers.handler import Handler


EARLY = bucket("monitors")
EARLY << [
    AliasFeature,
    MiniAppFeature,
    ChatCollectFeature,
    CurseMetricFeature,
    SilenceFeature,
    SilenceEnforcerFeature,
    BanFeature,
    BanEnforcerFeature,
    AiRelatedFeature,
    ReactionCounterFeature,
    UserMemoryFeature,
    HighcastCleanupFeature,
]


COMMANDS = bucket("commands")
COMMANDS << [
    SettingsFeature,
    AdminFeature,
    LangFeature,
    ArmyFeature,
    BillsFeature,
    BirthdayFeature,
    DbFeature,
    FeatureRequestFeature,
    MeFeature,
    StandsFeature,
    RewardFeature,
    TodoFeature,
    IncidentFeature,
    CurseFeature,
    IdFeature,
    PrettyTimeFeature,
    MessageInfoFeature,
    NewTextFeature,
    NewsVideoFeature,
    SubscribeFeature,
    TranslateFeature,
    LayoutFeature,
    TarotFeature,
    TennisFeature,
    ExchangeRateFeature,
    LinkFeature,
    TunnelFeature,
    RemindFeature,
    RemindersFeature,
    TimezoneFeature,
    HolidaysFeature,
    JokeFeature,
    EveryoneFeature,
    PashaFeature,
    DianaFeature,
    BroadcastFeature,
    AIFeature,
    VoiceVideoFeature,
    TranscribeFeature,
    ShazamFeature,
    TtsTestFeature,
    MultiplyFeature,
    FuckFeature,
    SexFeature,
    WatchFeature,
    DownloadFeature,
    GoogleDriveFeature,
    StatsFeature,
    ReactFeature,
    RuleFeature,
]


LATE = bucket("fallbacks")
LATE << [
    RuleAnswerFeature,
]


def all_features() -> list[Handler]:
    instances: list[Handler] = []
    for b in (EARLY, COMMANDS, LATE):
        for cls in b.list:
            instances.append(cls())
    return instances


# Логические группы: классы, которые тогглятся вместе (бан-команда + ban-enforcer
# и т.п.). Первый класс группы — primary, по нему берётся slug, label, описание.
CAPABILITIES_GROUPED: dict[str, list[list[type]]] = {
    "ai":         [[AIFeature], [AiRelatedFeature], [PashaFeature], [DianaFeature], [TranslateFeature]],
    "transcribe": [[TranscribeFeature], [ShazamFeature], [MultiplyFeature], [VoiceVideoFeature]],
    "rules":      [[RuleFeature, RuleAnswerFeature]],
    "fun":        [[JokeFeature], [TarotFeature], [FuckFeature], [SexFeature], [ReactFeature],
                   [WatchFeature], [EveryoneFeature], [TennisFeature]],
    "trackers":   [[ArmyFeature], [BillsFeature], [BirthdayFeature], [TodoFeature], [IncidentFeature],
                   [RemindFeature, RemindersFeature], [MeFeature], [RewardFeature], [StandsFeature],
                   [SubscribeFeature], [FeatureRequestFeature]],
    "chat_meta":  [[IdFeature], [MessageInfoFeature], [PrettyTimeFeature], [TimezoneFeature], [HolidaysFeature],
                   [ExchangeRateFeature], [LinkFeature], [TunnelFeature], [LayoutFeature], [NewTextFeature], [LangFeature]],
    "stats":      [[StatsFeature], [CurseFeature, CurseMetricFeature]],
    "downloads":  [[DownloadFeature], [GoogleDriveFeature]],
    "moderation": [[BanFeature, BanEnforcerFeature], [SilenceFeature, SilenceEnforcerFeature]],
}

CAPABILITIES: dict[str, set[type]] = {
    cap: {cls for group in groups for cls in group}
    for cap, groups in CAPABILITIES_GROUPED.items()
}


ALWAYS_ON: set[type] = {
    AdminFeature, MiniAppFeature, ChatCollectFeature,
    ReactionCounterFeature, UserMemoryFeature, HighcastCleanupFeature,
    DbFeature, BroadcastFeature,
}


CAPABILITY_LABELS: dict[str, str] = {
    "ai":         "AI-помощник",
    "transcribe": "Транскрибация",
    "rules":      "Правила-ответы",
    "fun":        "Развлечения",
    "trackers":   "Трекеры",
    "chat_meta":  "Утилиты чата",
    "stats":      "Статистика",
    "downloads":  "Скачивание",
    "moderation": "Модерация",
}


ALL_CAPABILITIES: set[str] = set(CAPABILITIES.keys())


def capability_of(feature_cls: type) -> str | None:
    for cap, classes in CAPABILITIES.items():
        if feature_cls in classes:
            return cap
    return None


def _group_of(feature_cls: type) -> list[type] | None:
    for groups in CAPABILITIES_GROUPED.values():
        for group in groups:
            if feature_cls in group:
                return group
    return None


def feature_group_primary(feature_cls: type) -> type:
    group = _group_of(feature_cls)
    return group[0] if group else feature_cls


def feature_slug(feature_cls: type) -> str:
    primary = feature_group_primary(feature_cls)
    return primary.__name__.removesuffix("Feature").lower()


def features_in_capability(cap: str) -> list[type]:
    """Primary class of each group inside the capability."""
    return [group[0] for group in CAPABILITIES_GROUPED.get(cap, [])]


def features_in_group(primary: type) -> list[type]:
    group = _group_of(primary)
    return list(group) if group else [primary]


def is_always_on(feature_cls: type) -> bool:
    if feature_cls in ALWAYS_ON:
        return True
    # SettingsFeature is registered lazily in COMMANDS; treat by name to avoid import cycle.
    return feature_cls.__name__ == "SettingsFeature"

from steward.features.admin import AdminFeature
from steward.features.ai import AIFeature
from steward.features.ai_related import AiRelatedFeature
from steward.features.army import ArmyFeature
from steward.features.ban import BanEnforcerFeature, BanFeature
from steward.features.birthday import BirthdayFeature
from steward.features.broadcast import BroadcastFeature
from steward.features.chat_collect import ChatCollectFeature
from steward.features.curse import CurseFeature
from steward.features.curse_metric import CurseMetricFeature
from steward.features.db import DbFeature
from steward.features.download import DownloadFeature
from steward.features.everyone import EveryoneFeature
from steward.features.exchange_rates import ExchangeRateFeature
from steward.features.feature_request import FeatureRequestFeature
from steward.features.google_drive import GoogleDriveFeature
from steward.features.holidays import HolidaysFeature
from steward.features.id import IdFeature
from steward.features.link import LinkFeature
from steward.features.me import MeFeature
from steward.features.message_info import MessageInfoFeature
from steward.features.miniapp import MiniAppFeature
from steward.features.multiply import MultiplyFeature
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
from steward.features.timezone import TimezoneFeature
from steward.features.todo import TodoFeature
from steward.features.translate import TranslateFeature
from steward.features.user_memory import UserMemoryFeature
from steward.features.voice_video import VoiceVideoFeature
from steward.features.watch import WatchFeature
from steward.framework import bucket
from steward.handlers.handler import Handler


EARLY = bucket("monitors")
EARLY << [
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
]


COMMANDS = bucket("commands")
COMMANDS << [
    AdminFeature,
    ArmyFeature,
    BirthdayFeature,
    DbFeature,
    FeatureRequestFeature,
    MeFeature,
    StandsFeature,
    RewardFeature,
    TodoFeature,
    CurseFeature,
    IdFeature,
    PrettyTimeFeature,
    MessageInfoFeature,
    NewTextFeature,
    SubscribeFeature,
    TranslateFeature,
    TarotFeature,
    ExchangeRateFeature,
    LinkFeature,
    RemindFeature,
    RemindersFeature,
    TimezoneFeature,
    HolidaysFeature,
    EveryoneFeature,
    PashaFeature,
    BroadcastFeature,
    AIFeature,
    VoiceVideoFeature,
    MultiplyFeature,
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

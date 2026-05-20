from dataclasses import dataclass
from typing import Any

from steward.bot.context import CallbackBotContext, ChatBotContext, ReactionBotContext

type SessionContext = dict[Any, Any]


@dataclass
class ChatStepContext(ChatBotContext):
    session_context: SessionContext


@dataclass
class CallbackStepContext(CallbackBotContext):
    session_context: SessionContext


@dataclass
class ReactionStepContext(ReactionBotContext):
    session_context: SessionContext


type StepContext = ChatStepContext | CallbackStepContext | ReactionStepContext

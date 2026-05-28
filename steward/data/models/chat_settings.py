from dataclasses import dataclass, field


@dataclass
class ChatSettings:
    chat_id: int
    enabled_capabilities: set[str] = field(default_factory=set)
    disabled_features: set[str] = field(default_factory=set)
    chat_admins: set[int] = field(default_factory=set)
    onboarded: bool = False

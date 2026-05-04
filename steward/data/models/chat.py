from dataclasses import dataclass, field


@dataclass
class Chat:
    id: int
    name: str
    aliases: list[str] = field(default_factory=list)

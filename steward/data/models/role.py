from dataclasses import dataclass, field


@dataclass
class Role:
    id: int
    name: str
    permissions: set[str] = field(default_factory=set)


@dataclass
class UserRole:
    user_id: int
    role_id: int

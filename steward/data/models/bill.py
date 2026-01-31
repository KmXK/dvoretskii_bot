from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Payment:
    person: str
    amount: float
    creditor: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Bill:
    id: int
    name: str
    file_id: str


@dataclass
class Transaction:
    item_name: str
    amount: float
    debtors: list[str]
    creditor: str


@dataclass
class DetailsInfo:
    name: str
    description: str

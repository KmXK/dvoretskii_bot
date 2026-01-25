from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Transaction:
    item_name: str
    amount: float
    debtors: list[str]
    creditor: str


@dataclass
class Payment:
    bill_id: int
    person: str
    amount: float
    creditor: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Optimization:
    debtor: str
    creditor: str
    amount: float


@dataclass
class Bill:
    id: int
    name: str
    transactions: list[Transaction] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    optimizations: list[Optimization] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DetailsInfo:
    name: str
    description: str

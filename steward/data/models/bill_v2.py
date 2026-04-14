from dataclasses import dataclass, field
from datetime import datetime, timedelta


UNKNOWN_PERSON_ID = "__unknown__"


class PaymentStatus:
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    AUTO_CONFIRMED = "auto_confirmed"

    SETTLED = {CONFIRMED, AUTO_CONFIRMED}


class TxSource:
    MANUAL = "manual"
    PHOTO = "photo"
    VOICE = "voice"
    TEXT = "text"
    AI = "ai"
    SHEET = "sheet"


class SuggestionStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class BillPerson:
    id: str                                         # UUID
    display_name: str
    telegram_id: int | None = None
    telegram_username: str | None = None
    username_updated_at: datetime | None = None
    aliases: list[str] = field(default_factory=list)
    description: str = ""                           # shared across chats (payment details etc.)
    chat_last_seen: dict[str, str] = field(default_factory=dict)
    # chat_id (str) -> ISO datetime of last bill activity in that chat.
    # Used only for ranking in person matching, never for ACL.


@dataclass
class BillItemAssignment:
    unit_count: int                                 # how many units this row covers
    debtors: list[str]                              # BillPerson.id; split equally; empty = unassigned


@dataclass
class BillTransaction:
    id: str
    item_name: str
    creditor: str                                   # BillPerson.id or UNKNOWN_PERSON_ID
    # Primary model: quantity-based assignments
    unit_price_minor: int = 0                       # price per unit in minor currency (kopecks for BYN)
    quantity: int = 1
    assignments: list[BillItemAssignment] = field(default_factory=list)
    # Metadata
    added_by_person_id: str | None = None
    source: str = "manual"                          # manual | photo | voice | text | ai | sheet
    created_at: datetime = field(default_factory=datetime.now)
    incomplete: bool = False                        # True if any assignment has empty debtors


@dataclass
class BillV2:
    id: int
    name: str
    author_person_id: str                           # BillPerson.id
    participants: list[str]                         # BillPerson.id list
    transactions: list[BillTransaction]
    created_at: datetime = field(default_factory=datetime.now)
    closed: bool = False
    closed_at: datetime | None = None
    currency: str = "BYN"                           # ISO 4217
    origin_chat_id: int | None = None               # scope-hint only, NOT used for access control
    updated_at: datetime = field(default_factory=datetime.now)
    last_incomplete_reminder_at: datetime | None = None


@dataclass
class BillPaymentV2:
    id: str
    debtor: str                                     # BillPerson.id
    creditor: str                                   # BillPerson.id
    amount_minor: int                               # in minor currency units
    status: str                                     # pending | confirmed | rejected | auto_confirmed
    created_at: datetime = field(default_factory=datetime.now)
    initiated_chat_id: int | None = None
    confirmation_chat_id: int | None = None
    confirmation_message_id: int | None = None
    reminder_sent_at: datetime | None = None
    bill_ids: list[int] = field(default_factory=list)
    currency: str = "BYN"


@dataclass
class BillItemSuggestion:
    id: str
    bill_id: int
    proposed_by_person_id: str
    proposed_tx: list[BillTransaction]
    status: str = "pending"                         # pending | approved | rejected | expired
    created_at: datetime = field(default_factory=datetime.now)
    decided_by_person_id: str | None = None
    decided_at: datetime | None = None
    origin_chat_id: int | None = None
    approval_message_id: int | None = None
    approval_chat_id: int | None = None
    bill_updated_at_propose: datetime | None = None  # for optimistic concurrency check


@dataclass
class BillDraftEdit:
    id: str                                         # UUID token
    bill_id: int
    author_person_id: str
    sheet_file_id: str
    share_url: str
    state_snapshot: dict                            # serialized BillV2 before edit
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(
        default_factory=lambda: datetime.now() + timedelta(hours=2)
    )
    merged: bool = False


@dataclass
class BillNotificationPrefs:
    telegram_id: int
    quiet_start: int = 0                            # hour 0–23
    quiet_end: int = 24                             # exclusive 0–24 (default: no quiet period)
    preferred_chat_ids: list[int] = field(default_factory=list)


@dataclass
class BillDiffSnapshot:
    token: str
    bill_id: int
    before: dict                                    # serialized BillV2 state
    after: dict                                     # serialized BillV2 state
    created_at: datetime = field(default_factory=datetime.now)

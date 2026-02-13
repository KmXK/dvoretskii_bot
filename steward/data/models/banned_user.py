from dataclasses import dataclass
from datetime import datetime


@dataclass
class BannedUser:
    chat_id: int
    user_id: int
    expires_at: datetime

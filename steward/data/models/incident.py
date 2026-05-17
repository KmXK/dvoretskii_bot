from dataclasses import dataclass
from typing import Optional


INCIDENT_STATUS_OPEN = "open"
INCIDENT_STATUS_RESOLVED = "resolved"


@dataclass
class Incident:
    id: int
    chat_id: int
    author_id: int
    text: str
    created_at: float
    status: str = INCIDENT_STATUS_OPEN
    closed_at: Optional[float] = None
    closed_by: Optional[int] = None

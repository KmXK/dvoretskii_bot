from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional


@dataclass
class SavedLink:
    link: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expire_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=30)
    )


@dataclass
class SavedLinks:
    """Container for saved links with TTL pruning and JSON (de)serialization.

    Behavior:
    - stores mapping key -> SavedLink
    - automatically prunes expired items on add/get/serialize
    - serializes datetimes as ISO strings so `json` can encode them
    """

    links: Dict[str, SavedLink] = field(default_factory=dict)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def prune(self) -> None:
        """Remove keys older than TTL."""
        now = self._now()
        to_delete = [k for k, v in self.links.items() if v.expire_at <= now]
        for k in to_delete:
            del self.links[k]

    def add(self, key: str, link: str, ttl: timedelta = timedelta(days=30)) -> None:
        """Add or replace a saved link (prunes old entries first)."""
        self.prune()
        self.links[key] = SavedLink(
            link=link,
            created_at=self._now(),
            expire_at=self._now() + ttl,
        )

    def get(self, key: str) -> Optional[str]:
        """Return link or None. Prunes expired items first."""
        self.prune()
        entry = self.links.get(key)
        return entry.link if entry is not None else None

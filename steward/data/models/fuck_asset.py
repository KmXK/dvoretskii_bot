from dataclasses import dataclass


@dataclass
class FuckAsset:
    id: str
    owner_id: int
    name: str
    scope: str
    extension: str
    created_at: int

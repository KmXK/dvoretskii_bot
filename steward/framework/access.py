from dataclasses import dataclass
from enum import Enum


class AccessMode(str, Enum):
    OPEN = "open"
    INITIATOR_ONLY = "initiator_only"
    RESOURCE_AUTHOR = "resource_author"


@dataclass(frozen=True)
class AccessPolicy:
    mode: AccessMode = AccessMode.OPEN
    initiator_field: str = "initiator"
    resource_field: str = ""
    admin_bypass: bool = False


OPEN = AccessPolicy()
INITIATOR_ONLY = AccessPolicy(mode=AccessMode.INITIATOR_ONLY)


def initiator_only(field: str = "initiator", *, admin_bypass: bool = False) -> AccessPolicy:
    return AccessPolicy(
        mode=AccessMode.INITIATOR_ONLY,
        initiator_field=field,
        admin_bypass=admin_bypass,
    )


def resource_author(field: str, *, admin_bypass: bool = False) -> AccessPolicy:
    if not field:
        raise ValueError("resource_author requires a non-empty field name")
    return AccessPolicy(
        mode=AccessMode.RESOURCE_AUTHOR,
        resource_field=field,
        admin_bypass=admin_bypass,
    )

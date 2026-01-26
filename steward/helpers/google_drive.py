import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_GKEYS_PATH = Path(__file__).resolve().parent.parent.parent / "gkeys.json"
_AVAILABLE = _GKEYS_PATH.is_file()

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def is_available() -> bool:
    return _AVAILABLE


def _drive_service():
    if not _AVAILABLE:
        return None
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    with open(_GKEYS_PATH, "r") as f:
        info = json.load(f)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def list_drive_files() -> list[dict] | None:
    if not _AVAILABLE:
        return None
    try:
        service = _drive_service()
        results = (
            service.files()
            .list(
                q="trashed=false",
                fields="files(id, name, mimeType, createdTime)",
                pageSize=1000,
            )
            .execute()
        )
        return results.get("files", [])
    except Exception as e:
        logger.exception("list_drive_files: %s", e)
        return None

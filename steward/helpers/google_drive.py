import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_GKEYS_PATH = Path(__file__).resolve().parent.parent.parent / "gkeys.json"
_AVAILABLE = _GKEYS_PATH.is_file()

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def is_available() -> bool:
    return _AVAILABLE


def _drive_service():
    if not _AVAILABLE:
        return None
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        str(_GKEYS_PATH), scopes=SCOPES
    )
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
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        return results.get("files", [])
    except Exception as e:
        logger.exception("list_drive_files: %s", e)
        return None


def find_folder_by_name(folder_name: str) -> str | None:
    if not _AVAILABLE:
        return None
    try:
        service = _drive_service()
        results = (
            service.files()
            .list(
                q="mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = results.get("files", [])
        folder_name_lower = folder_name.lower()
        for file in files:
            if file.get("name", "").lower() == folder_name_lower:
                return file["id"]
        return None
    except Exception as e:
        logger.exception("find_folder_by_name: %s", e)
        return None


def find_file_in_folder(folder_id: str, file_name: str) -> str | None:
    if not _AVAILABLE:
        return None
    try:
        service = _drive_service()
        results = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = results.get("files", [])
        file_name_lower = file_name.lower()
        for file in files:
            if file.get("name", "").lower() == file_name_lower:
                return file["id"]
        return None
    except Exception as e:
        logger.exception("find_file_in_folder: %s", e)
        return None


def find_files_in_folder_by_name(folder_id: str, file_name: str) -> list[str]:
    if not _AVAILABLE:
        return []
    try:
        service = _drive_service()
        results = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = results.get("files", [])
        file_name_lower = file_name.lower()
        return [
            file["id"]
            for file in files
            if file.get("name", "").lower() == file_name_lower and file.get("id")
        ]
    except Exception as e:
        logger.exception("find_files_in_folder_by_name: %s", e)
        return []


def rename_file(file_id: str, new_name: str) -> tuple[str | None, str | None]:
    if not _AVAILABLE:
        return None, "Google Drive недоступен"
    try:
        service = _drive_service()
        updated = (
            service.files()
            .update(
                fileId=file_id,
                body={"name": new_name},
                fields="id,name",
                supportsAllDrives=True,
            )
            .execute()
        )
        updated_file_id = updated.get("id")
        if not updated_file_id:
            return None, "Не удалось получить ID переименованного файла"
        return updated_file_id, None
    except Exception as e:
        logger.exception("rename_file: %s", e)
        return None, f"Ошибка при переименовании файла: {e}"


def create_file(
    file_name: str, parent_folder_id: str | None = None, mime_type: str = "application/vnd.google-apps.spreadsheet"
) -> tuple[str | None, str | None]:
    if not _AVAILABLE:
        return None, "Google Drive недоступен"
    try:
        service = _drive_service()
        file_metadata = {"name": file_name, "mimeType": mime_type}
        if parent_folder_id:
            file_metadata["parents"] = [parent_folder_id]

        new_file = (
            service.files()
            .create(
                body=file_metadata,
                supportsAllDrives=True,
                fields="id, name, parents"
            )
            .execute()
        )
        new_file_id = new_file.get("id")
        if not new_file_id:
            return None, "Не удалось получить ID созданного файла"
        return new_file_id, None
    except Exception as e:
        logger.exception("create_file: %s", e)
        try:
            from googleapiclient.errors import HttpError

            if isinstance(e, HttpError):
                error_content = (
                    e.content.decode("utf-8")
                    if hasattr(e, "content") and e.content
                    else str(e)
                )
                error_details = []

                try:
                    import json

                    if hasattr(e, "error_details"):
                        error_details = e.error_details
                    elif hasattr(e, "content"):
                        error_data = (
                            json.loads(error_content)
                            if isinstance(error_content, str)
                            else {}
                        )
                        error_details = error_data.get("error", {}).get("errors", [])
                except Exception:
                    pass

                for detail in error_details:
                    reason = (
                        detail.get("reason", "") if isinstance(detail, dict) else ""
                    )
                    if reason == "storageQuotaExceeded":
                        return (
                            None,
                            "Превышена квота хранилища Google Drive. Освободите место и попробуйте снова.",
                        )
                    if reason == "userRateLimitExceeded":
                        return (
                            None,
                            "Превышен лимит запросов к Google Drive. Попробуйте позже.",
                        )
        except ImportError:
            pass

        error_msg = str(e)
        if (
            "storageQuotaExceeded" in error_msg
            or "storage quota" in error_msg.lower()
            or "quota exceeded" in error_msg.lower()
        ):
            return (
                None,
                "Превышена квота хранилища Google Drive. Освободите место и попробуйте снова.",
            )

        return None, f"Ошибка при создании файла: {error_msg}"


def _drive_instance():
    if not _AVAILABLE:
        return None
    from pydrive.auth import GoogleAuth
    from pydrive.drive import GoogleDrive
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    gauth = GoogleAuth()
    creds = service_account.Credentials.from_service_account_file(
        str(_GKEYS_PATH), scopes=SCOPES
    )
    gauth.credentials = creds
    gauth.service = build("drive", "v3", credentials=creds)
    return GoogleDrive(gauth)


def copy_file(
    file_id: str, new_name: str | None = None, parent_folder_id: str | None = None
) -> tuple[str | None, str | None]:
    if not _AVAILABLE:
        return None, "Google Drive недоступен"
    try:
        drive = _drive_instance()
        if not drive:
            return None, "Google Drive недоступен"
        
        body = {}
        if new_name:
            body["title"] = new_name
        if parent_folder_id:
            body["parents"] = [{"kind": "drive#fileLink", "id": parent_folder_id}]

        copied_file = drive.auth.service.files().copy(
            fileId=file_id,
            body=body
        ).execute()
        
        new_file_id = copied_file.get("id")
        if not new_file_id:
            return None, "Не удалось получить ID созданного файла"
        return new_file_id, None
    except Exception as e:
        logger.exception("copy_file: %s", e)
        try:
            from googleapiclient.errors import HttpError

            if isinstance(e, HttpError):
                error_content = (
                    e.content.decode("utf-8")
                    if hasattr(e, "content") and e.content
                    else str(e)
                )
                error_details = []

                try:
                    import json

                    if hasattr(e, "error_details"):
                        error_details = e.error_details
                    elif hasattr(e, "content"):
                        error_data = (
                            json.loads(error_content)
                            if isinstance(error_content, str)
                            else {}
                        )
                        error_details = error_data.get("error", {}).get("errors", [])
                except Exception:
                    pass

                for detail in error_details:
                    reason = (
                        detail.get("reason", "") if isinstance(detail, dict) else ""
                    )
                    if reason == "storageQuotaExceeded":
                        return (
                            None,
                            "Превышена квота хранилища Google Drive. Освободите место и попробуйте снова.",
                        )
                    if reason == "userRateLimitExceeded":
                        return (
                            None,
                            "Превышен лимит запросов к Google Drive. Попробуйте позже.",
                        )
        except ImportError:
            pass

        error_msg = str(e)
        if (
            "storageQuotaExceeded" in error_msg
            or "storage quota" in error_msg.lower()
            or "quota exceeded" in error_msg.lower()
        ):
            return (
                None,
                "Превышена квота хранилища Google Drive. Освободите место и попробуйте снова.",
            )

        return None, f"Ошибка при копировании файла: {error_msg}"


def share_file_with_anyone(file_id: str) -> bool:
    if not _AVAILABLE:
        return False
    try:
        service = _drive_service()
        permission = {"type": "anyone", "role": "writer"}
        service.permissions().create(
            fileId=file_id,
            body=permission,
            supportsAllDrives=True,
            fields="id"
        ).execute()
        logger.info(f"Права доступа предоставлены для файла {file_id}")
        return True
    except Exception as e:
        logger.exception("share_file_with_anyone: %s", e)
        try:
            from googleapiclient.errors import HttpError

            if isinstance(e, HttpError):
                error_msg = str(e)
                if (
                    "Permission denied" in error_msg
                    or "insufficientFilePermissions" in error_msg
                ):
                    logger.warning(
                        f"Не удалось предоставить права для файла {file_id}, возможно файл уже доступен"
                    )
                    return False
        except ImportError:
            pass
        return False


def get_file_link(file_id: str) -> str | None:
    if not _AVAILABLE:
        return None
    try:
        service = _drive_service()
        file = (
            service.files()
            .get(
                fileId=file_id,
                fields="webViewLink, webContentLink, mimeType",
                supportsAllDrives=True,
            )
            .execute()
        )

        web_view_link = file.get("webViewLink")
        if web_view_link:
            return web_view_link

        mime_type = file.get("mimeType", "")
        if "spreadsheet" in mime_type:
            return f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
        elif "document" in mime_type:
            return f"https://docs.google.com/document/d/{file_id}/edit"
        else:
            return f"https://drive.google.com/file/d/{file_id}/view"
    except Exception as e:
        logger.exception("get_file_link: %s", e)
        return f"https://drive.google.com/file/d/{file_id}/view"


def read_spreadsheet_values(spreadsheet_id: str) -> list[list[str]] | None:
    if not _AVAILABLE:
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            str(_GKEYS_PATH), scopes=SCOPES
        )
        service = build("sheets", "v4", credentials=creds)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range="A:Z")
            .execute()
        )
        return result.get("values", [])
    except Exception as e:
        logger.exception("read_spreadsheet_values: %s", e)
        return None


def _sheet_range(sheet_name: str, cell_range: str) -> str:
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'!{cell_range}"


def read_spreadsheet_values_from_sheet(
    spreadsheet_id: str,
    sheet_name: str,
    cell_range: str = "A:Z",
) -> list[list[str]] | None:
    if not _AVAILABLE:
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            str(_GKEYS_PATH), scopes=SCOPES
        )
        service = build("sheets", "v4", credentials=creds)
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=_sheet_range(sheet_name, cell_range),
            )
            .execute()
        )
        return result.get("values", [])
    except Exception as e:
        logger.exception("read_spreadsheet_values_from_sheet: %s", e)
        return None


def _sheets_service():
    if not _AVAILABLE:
        return None
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        str(_GKEYS_PATH), scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def _column_letter_to_index(column: str) -> int:
    idx = 0
    for ch in column.upper():
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"Invalid column: {column}")
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _index_to_column_letter(index: int) -> str:
    if index < 0:
        raise ValueError(f"Invalid column index: {index}")
    out = []
    value = index + 1
    while value > 0:
        value, rem = divmod(value - 1, 26)
        out.append(chr(ord("A") + rem))
    return "".join(reversed(out))


def insert_rows_into_spreadsheet(
    spreadsheet_id: str, rows: list[list[str]]
) -> bool:
    if not _AVAILABLE or not rows:
        return False
    try:
        service = _sheets_service()

        existing = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range="A:A")
            .execute()
        )
        values = existing.get("values", [])
        first_empty = len(values)
        for i, row in enumerate(values):
            if not row or not row[0].strip():
                first_empty = i
                break

        meta = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties.sheetId",
        ).execute()
        sheet_id = meta["sheets"][0]["properties"]["sheetId"]

        count = len(rows)
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "insertDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": first_empty,
                                "endIndex": first_empty + count,
                            },
                            "inheritFromBefore": True,
                        }
                    }
                ]
            },
        ).execute()

        cell_range = f"A{first_empty + 1}:B{first_empty + count}"
        result = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=cell_range,
                valueInputOption="USER_ENTERED",
                body={"values": rows},
            )
            .execute()
        )
        logger.info("insert_rows_into_spreadsheet: inserted %d rows at %d, result: %s",
                     count, first_empty, result)
        return result.get("updatedRows", 0) > 0
    except Exception as e:
        logger.exception("insert_rows_into_spreadsheet: %s", e)
        return False


def insert_rows_into_sheet(
    spreadsheet_id: str,
    rows: list[list[str]],
    sheet_name: str,
    start_column: str = "A",
) -> bool:
    if not _AVAILABLE or not rows:
        return False
    try:
        service = _sheets_service()

        existing = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=_sheet_range(sheet_name, f"{start_column}:{start_column}"),
            )
            .execute()
        )
        values = existing.get("values", [])
        first_empty = len(values)
        for i, row in enumerate(values):
            if not row or not row[0].strip():
                first_empty = i
                break

        meta = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties(sheetId,title)",
        ).execute()
        sheet_id = None
        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == sheet_name:
                sheet_id = props.get("sheetId")
                break
        if sheet_id is None:
            logger.error("insert_rows_into_sheet: sheet '%s' not found", sheet_name)
            return False

        count = len(rows)
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "insertDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": first_empty,
                                "endIndex": first_empty + count,
                            },
                            "inheritFromBefore": True,
                        }
                    }
                ]
            },
        ).execute()

        width = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (width - len(row)) for row in rows]
        start_col_idx = _column_letter_to_index(start_column)
        end_col = _index_to_column_letter(start_col_idx + width - 1)
        cell_range = _sheet_range(
            sheet_name,
            f"{start_column}{first_empty + 1}:{end_col}{first_empty + count}",
        )
        result = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=cell_range,
                valueInputOption="USER_ENTERED",
                body={"values": normalized_rows},
            )
            .execute()
        )
        return result.get("updatedRows", 0) > 0
    except Exception as e:
        logger.exception("insert_rows_into_sheet: %s", e)
        return False


def list_files_in_folder(folder_id: str) -> list[tuple[str, str]]:
    if not _AVAILABLE:
        return []
    try:
        service = _drive_service()
        results = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = results.get("files", [])
        return [(f["id"], f["name"]) for f in files]
    except Exception as e:
        logger.exception("list_files_in_folder: %s", e)
        return []

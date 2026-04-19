from steward.data.models.bill import Bill, Transaction
from steward.features.bills.amounts import normalize_name, parse_amount
from steward.helpers.google_drive import (
    read_spreadsheet_values,
    read_spreadsheet_values_from_sheet,
)


FINANCES_FOLDER_ID = "1_YgOgjiqOyMZ1_jVAND_7HG9GfE7MpHX"
BILL_MAIN_SHEET_NAME = "Общее"
BILL_DATA_SHEET_NAME = "Данные"
BILL_DATA_SHEET_NAME_FALLBACK = "данные"
BILL_TEMPLATE_FILE_NAME = "Копия Шаблон"


def get_bills_folder_id() -> str:
    return FINANCES_FOLDER_ID


def read_bill_raw_rows(file_id: str) -> list[list[str]]:
    rows = read_spreadsheet_values_from_sheet(file_id, BILL_MAIN_SHEET_NAME)
    if rows is None:
        rows = read_spreadsheet_values(file_id)
    return rows or []


def read_bill_people_places_rows(file_id: str) -> list[list[str]]:
    rows = read_spreadsheet_values_from_sheet(file_id, BILL_DATA_SHEET_NAME)
    if rows is None:
        rows = read_spreadsheet_values_from_sheet(file_id, BILL_DATA_SHEET_NAME_FALLBACK)
    return rows or []


def parse_transactions_from_sheet(rows: list[list[str]]) -> list[Transaction]:
    out = []
    for i, row in enumerate(rows):
        if i == 0 and row and "Наименование" in (row[0] if row else ""):
            continue
        if len(row) < 4:
            continue
        item_name = (row[0] or "").strip()
        if not item_name:
            continue
        try:
            amount = parse_amount(row[1] or "0")
        except ValueError:
            continue
        debtors_str = (row[2] or "").strip()
        debtors = [d.strip() for d in debtors_str.split(",") if d.strip()]
        creditor = (row[3] or "").strip()
        if not debtors or not creditor:
            continue
        out.append(
            Transaction(
                item_name=item_name,
                amount=amount,
                debtors=debtors,
                creditor=creditor,
            )
        )
    return out


def parse_people_places(rows: list[list[str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        if not row:
            continue
        person = (row[0] if len(row) > 0 else "").strip()
        place = (row[1] if len(row) > 1 else "").strip()
        if not person:
            continue
        if normalize_name(person) in {"персонаж", "действующее лицо"}:
            continue
        result[person] = place
    return result


def parse_known_places(rows: list[list[str]]) -> list[str]:
    places: list[str] = []
    seen: set[str] = set()
    places_only_mode = False
    for row in rows:
        if not row:
            continue
        col1 = (row[0] if len(row) > 0 else "").strip()
        col2 = (row[1] if len(row) > 1 else "").strip()
        col1_norm = normalize_name(col1)
        if col1_norm == "места":
            places_only_mode = True
            continue
        if col1_norm in {"персонаж", "действующее лицо"}:
            continue
        candidate = ""
        if places_only_mode and col1:
            candidate = col1
        elif col2:
            candidate = col2
        if not candidate:
            continue
        key = normalize_name(candidate)
        if key and key not in seen:
            seen.add(key)
            places.append(candidate)
    return places


def load_bill_transactions(file_id: str) -> list[Transaction]:
    rows = read_bill_raw_rows(file_id)
    if rows:
        rows = rows[:-1]
    return parse_transactions_from_sheet(rows)


def load_all_transactions(bills: list[Bill]) -> list[Transaction]:
    all_tx = []
    for bill in bills:
        all_tx.extend(load_bill_transactions(bill.file_id))
    return all_tx


def format_debug_rows(rows: list[list[str]], bill_name: str) -> str:
    lines = [f"🔍 DEBUG [{bill_name}] — строки из таблицы:"]
    if not rows:
        lines.append("(пусто)")
    else:
        for i, row in enumerate(rows):
            row_str = (
                " | ".join(str(cell) for cell in row) if row else "(пустая строка)"
            )
            lines.append(f"{i}: {row_str}")
    return "\n".join(lines)

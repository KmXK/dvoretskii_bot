"""One-shot migration: legacy Sheets-backed Bill/Payment/DetailsInfo → bill_v2.

Reads db.json + the Google Sheets each Bill points at, builds BillV2 /
BillTransaction / BillPerson / BillPaymentV2 records, and writes them
back to db.json (or prints a preview in --dry-run mode).

Usage (from repo root):

    ./venv/bin/python -m scripts.migrate_bills_to_v2                  # dry-run
    ./venv/bin/python -m scripts.migrate_bills_to_v2 --apply          # write
    ./venv/bin/python -m scripts.migrate_bills_to_v2 --db other.json  # custom db
    ./venv/bin/python -m scripts.migrate_bills_to_v2 --apply --force  # override
                                                                       # the
                                                                       # already-
                                                                       # migrated
                                                                       # guard

Requirements:
- gkeys.json with Drive/Sheets scopes in repo root (steward.helpers.google_drive).
- db.json already at version >= 14 (run the bot once to apply migrations).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from steward.data.models.bill_v2 import (
    UNKNOWN_PERSON_ID,
    BillItemAssignment,
    BillPaymentV2,
    BillPerson,
    BillTransaction,
    BillV2,
    PaymentStatus,
    TxSource,
)
from steward.helpers import google_drive as gd

logger = logging.getLogger(__name__)


_AMOUNT_RE = re.compile(r"[\d\s]+[,.]?\d*")
_DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})"),
    re.compile(r"(?P<d>\d{1,2})[-./](?P<m>\d{1,2})[-./](?P<y>20\d{2})"),
    re.compile(r"(?P<d>\d{1,2})[-./](?P<m>\d{1,2})[-./](?P<y>\d{2})\b"),
]
_RU_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "май": 5,
    "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10,
    "ноябр": 11, "декабр": 12,
}


def parse_amount(s: str) -> float:
    s = s.strip().replace(" ", " ").replace(",", ".")
    m = _AMOUNT_RE.search(s)
    if not m:
        raise ValueError(f"unparseable amount: {s!r}")
    raw = m.group(0).replace(" ", "").strip()
    value = float(raw)
    if "-" in s[: m.start()]:
        value = -value
    return value


def parse_date_from_name(name: str) -> datetime | None:
    """Best-effort date extraction from a bill name."""
    for pat in _DATE_PATTERNS:
        m = pat.search(name)
        if not m:
            continue
        try:
            y = int(m.group("y"))
            if y < 100:
                y += 2000
            return datetime(y, int(m.group("m")), int(m.group("d")))
        except (ValueError, KeyError):
            continue
    # "Декабрь 2024", "декабря 2024"
    name_l = name.lower()
    for stem, mnum in _RU_MONTHS.items():
        if stem in name_l:
            ym = re.search(r"(20\d{2})", name)
            if ym:
                return datetime(int(ym.group(1)), mnum, 1)
    return None


def fetch_gd_created_time(file_id: str) -> datetime | None:
    """Fetch the GD createdTime of a spreadsheet. Returns None on failure."""
    if not gd.is_available():
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            str(gd._GKEYS_PATH), scopes=gd.SCOPES
        )
        service = build("drive", "v3", credentials=creds)
        meta = (
            service.files()
            .get(
                fileId=file_id,
                fields="createdTime, modifiedTime",
                supportsAllDrives=True,
            )
            .execute()
        )
        ts = meta.get("createdTime") or meta.get("modifiedTime")
        if not ts:
            return None
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception as e:
        logger.warning("fetch_gd_created_time(%s) failed: %s", file_id, e)
        return None


def parse_transactions_from_rows(rows: list[list[str]]) -> tuple[list[dict], list[str]]:
    """Parse the «Общее» rows (excluding trailing total row).

    Returns (transactions, warnings). Each transaction is a dict with
    {item_name, amount, debtors, creditor}.
    """
    out: list[dict] = []
    warns: list[str] = []
    if not rows:
        return out, warns
    # Drop trailing total row (legacy load_bill_transactions did this).
    if rows:
        rows = rows[:-1]
    for i, row in enumerate(rows):
        if i == 0 and row and "Наименование" in (row[0] or ""):
            continue
        if len(row) < 4:
            continue
        item_name = (row[0] or "").strip()
        if not item_name:
            continue
        try:
            amount = parse_amount(row[1] or "0")
        except ValueError:
            warns.append(f"row {i}: unparseable amount in {row!r}")
            continue
        debtors_str = (row[2] or "").strip()
        debtors = [d.strip() for d in debtors_str.split(",") if d.strip()]
        creditor = (row[3] or "").strip()
        if not debtors or not creditor:
            warns.append(f"row {i}: missing debtors/creditor in {row!r}")
            continue
        out.append({
            "item_name": item_name,
            "amount": amount,
            "debtors": debtors,
            "creditor": creditor,
        })
    return out, warns


def parse_persons_directory(rows: list[list[str]]) -> list[str]:
    """Extract person names from the «Данные» sheet (header + person|place rows)."""
    out: list[str] = []
    seen: set[str] = set()
    for i, row in enumerate(rows):
        if not row:
            continue
        name = (row[0] or "").strip()
        if not name:
            continue
        nlow = name.lower()
        if i == 0 and nlow in {"персонаж", "действующее лицо", "места"}:
            continue
        if nlow in {"персонаж", "действующее лицо", "места"}:
            continue
        if nlow in seen:
            continue
        seen.add(nlow)
        out.append(name)
    return out


class PersonResolver:
    """Resolves a free-text name string to a BillPerson, creating anons when needed."""

    def __init__(self, db: dict[str, Any]):
        self.db = db
        self.bill_persons: list[dict] = list(db.get("bill_persons", []))
        self.users: list[dict] = list(db.get("users", []))
        self._created_count = 0
        self._matched_to_user: list[tuple[str, str]] = []  # (input_name, display_name)

        # Pre-build lookup tables (lower-cased).
        self._bp_by_name: dict[str, dict] = {}
        for p in self.bill_persons:
            self._bp_by_name.setdefault(p["display_name"].lower(), p)
            for alias in p.get("aliases", []) or []:
                self._bp_by_name.setdefault(alias.lower(), p)

        self._user_by_alias: dict[str, dict] = {}
        for u in self.users:
            sn = (u.get("stand_name") or "").strip()
            if sn:
                self._user_by_alias.setdefault(sn.lower(), u)
            for a in u.get("stand_aliases", []) or []:
                if a.strip():
                    self._user_by_alias.setdefault(a.lower(), u)
            un = (u.get("username") or "").strip()
            if un:
                self._user_by_alias.setdefault(un.lower(), u)

    def resolve(self, raw: str) -> dict:
        name = raw.strip()
        if not name:
            return self._unknown()
        key = name.lower().lstrip("@")

        existing = self._bp_by_name.get(key)
        if existing:
            return existing

        user = self._user_by_alias.get(key)
        if user:
            display_name = (user.get("stand_name") or user.get("username") or str(user["id"])).strip()
            person = self._make_person(
                display_name=display_name or name,
                telegram_id=user["id"],
                telegram_username=user.get("username"),
                aliases=[a for a in (user.get("stand_aliases") or []) if a],
            )
            self._matched_to_user.append((name, person["display_name"]))
            self._index(person, key, name)
            return person

        # Anonymous fallback.
        person = self._make_person(
            display_name=name,
            telegram_id=None,
            telegram_username=None,
            aliases=[],
        )
        self._index(person, key, name)
        return person

    def _make_person(
        self,
        display_name: str,
        telegram_id: int | None,
        telegram_username: str | None,
        aliases: list[str],
    ) -> dict:
        person = {
            "id": str(uuid.uuid4()),
            "display_name": display_name,
            "telegram_id": telegram_id,
            "telegram_username": telegram_username,
            "username_updated_at": None,
            "aliases": list(aliases),
            "description": "",
            "chat_last_seen": {},
        }
        self.bill_persons.append(person)
        self._created_count += 1
        return person

    def _index(self, person: dict, key: str, name: str) -> None:
        self._bp_by_name.setdefault(key, person)
        # Also index display_name for next caller asking with the canonical form.
        self._bp_by_name.setdefault(person["display_name"].lower(), person)

    def _unknown(self) -> dict:
        # Return a sentinel non-persisted person; callers should treat as missing.
        return {
            "id": UNKNOWN_PERSON_ID,
            "display_name": "?",
            "telegram_id": None,
            "telegram_username": None,
            "username_updated_at": None,
            "aliases": [],
            "description": "",
            "chat_last_seen": {},
        }

    @property
    def created_count(self) -> int:
        return self._created_count

    @property
    def matched_to_user(self) -> list[tuple[str, str]]:
        return self._matched_to_user


def to_minor(amount: float) -> int:
    return int(round(amount * 100))


def make_bill_v2(
    bill: dict,
    transactions_rows: list[dict],
    resolver: PersonResolver,
    created_at: datetime,
) -> tuple[dict, list[str]]:
    """Build a BillV2 dict + per-row warnings. Mutates resolver to add new persons."""
    warnings: list[str] = []
    txs: list[dict] = []
    participants: set[str] = set()

    for row in transactions_rows:
        creditor_p = resolver.resolve(row["creditor"])
        if creditor_p["id"] == UNKNOWN_PERSON_ID:
            warnings.append(f"item {row['item_name']!r}: unresolved creditor {row['creditor']!r}")
            continue
        debtor_ids: list[str] = []
        for d in row["debtors"]:
            dp = resolver.resolve(d)
            if dp["id"] == UNKNOWN_PERSON_ID:
                warnings.append(f"item {row['item_name']!r}: unresolved debtor {d!r}")
                continue
            debtor_ids.append(dp["id"])
            participants.add(dp["id"])
        if not debtor_ids:
            warnings.append(f"item {row['item_name']!r}: no debtors after resolve, skipped")
            continue
        participants.add(creditor_p["id"])

        tx = {
            "id": str(uuid.uuid4()),
            "item_name": row["item_name"],
            "creditor": creditor_p["id"],
            "unit_price_minor": to_minor(row["amount"]),
            "quantity": 1,
            "assignments": [
                {"unit_count": 1, "debtors": list(debtor_ids)},
            ],
            "added_by_person_id": None,
            "source": TxSource.SHEET,
            "incomplete": False,
        }
        txs.append(tx)

    bill_v2 = {
        "id": bill["id"],
        "name": bill["name"],
        "author_person_id": UNKNOWN_PERSON_ID,
        "participants": sorted(participants),
        "transactions": txs,
        "created_at": created_at.isoformat(),
        "closed": False,
        "closed_at": None,
        "currency": "BYN",
        "origin_chat_id": None,
        "updated_at": created_at.isoformat(),
        "last_incomplete_reminder_at": None,
    }
    return bill_v2, warnings


def make_payment_v2(payment: dict, resolver: PersonResolver) -> tuple[dict | None, list[str]]:
    debtor_p = resolver.resolve(payment.get("person") or "")
    if debtor_p["id"] == UNKNOWN_PERSON_ID:
        return None, [f"payment: unresolved debtor {payment.get('person')!r}"]
    creditor_id = UNKNOWN_PERSON_ID
    if payment.get("creditor"):
        cp = resolver.resolve(payment["creditor"])
        creditor_id = cp["id"]

    ts = payment.get("timestamp")
    if isinstance(ts, str):
        try:
            created_at = datetime.fromisoformat(ts).isoformat()
        except ValueError:
            created_at = datetime.now().isoformat()
    elif isinstance(ts, (int, float)):
        created_at = datetime.fromtimestamp(ts).isoformat()
    else:
        created_at = datetime.now().isoformat()

    return {
        "id": str(uuid.uuid4()),
        "debtor": debtor_p["id"],
        "creditor": creditor_id,
        "amount_minor": to_minor(float(payment.get("amount") or 0)),
        "status": PaymentStatus.CONFIRMED,
        "created_at": created_at,
        "initiated_chat_id": None,
        "confirmation_chat_id": None,
        "confirmation_message_id": None,
        "reminder_sent_at": None,
        "bill_ids": [],
        "currency": "BYN",
    }, []


def apply_details_infos(infos: list[dict], resolver: PersonResolver) -> int:
    n = 0
    for info in infos:
        name = (info.get("name") or "").strip()
        desc = (info.get("description") or "").strip()
        if not name or not desc:
            continue
        person = resolver.resolve(name)
        if person["id"] == UNKNOWN_PERSON_ID:
            continue
        if not person.get("description"):
            person["description"] = desc
            n += 1
    return n


def _bill_created_at(bill: dict) -> datetime:
    """Resolve created_at via name → GD createdTime → now()."""
    name = bill.get("name", "")
    dt = parse_date_from_name(name)
    if dt:
        return dt
    file_id = bill.get("file_id")
    if file_id:
        dt = fetch_gd_created_time(file_id)
        if dt:
            return dt
    return datetime.now()


def run_migration(db_path: Path, apply: bool, force: bool) -> int:
    print(f"=== Loading {db_path} ===")
    if not db_path.exists():
        print(f"db file not found: {db_path}", file=sys.stderr)
        return 2
    db = json.loads(db_path.read_text(encoding="utf-8"))

    if db.get("version", 0) < 14:
        print(
            f"db.version={db.get('version')} — run the bot once first so v14 migration applies.",
            file=sys.stderr,
        )
        return 2

    bills = list(db.get("bills", []))
    payments = list(db.get("payments", []))
    details_infos = list(db.get("details_infos", []))
    bills_v2 = list(db.get("bills_v2", []))
    payments_v2 = list(db.get("bill_payments_v2", []))

    print(
        f"  legacy: {len(bills)} bills, {len(payments)} payments, "
        f"{len(details_infos)} details_infos"
    )
    print(
        f"  v2 already: {len(bills_v2)} bills_v2, {len(payments_v2)} bill_payments_v2"
    )

    if (bills_v2 or payments_v2) and not force:
        print(
            "ABORT: bills_v2 / bill_payments_v2 already populated. "
            "Pass --force to migrate anyway (will append).",
            file=sys.stderr,
        )
        return 3

    if not gd.is_available():
        print(
            "WARNING: gkeys.json missing — cannot fetch Sheets. "
            "Bills with file_id will be skipped.",
            file=sys.stderr,
        )

    resolver = PersonResolver(db)

    new_bills_v2: list[dict] = []
    new_payments_v2: list[dict] = []
    all_warnings: list[str] = []
    skipped: list[tuple[int, str, str]] = []  # (bill_id, name, reason)

    print(f"\n=== Bills ({len(bills)}) ===")
    for bill in bills:
        bid = bill.get("id")
        name = bill.get("name", "?")
        file_id = bill.get("file_id")
        print(f"\n  Bill #{bid}: «{name}» (file_id={file_id})")

        if not file_id:
            print(f"    SKIP: no file_id")
            skipped.append((bid, name, "no file_id"))
            continue

        rows = gd.read_spreadsheet_values_from_sheet(file_id, "Общее")
        if not rows:
            rows = gd.read_spreadsheet_values(file_id)
        if not rows:
            print(f"    SKIP: could not fetch Sheets data")
            skipped.append((bid, name, "fetch failed"))
            continue
        print(f"    fetched {len(rows)} rows")

        # Pre-load directory.
        dir_rows = (
            gd.read_spreadsheet_values_from_sheet(file_id, "Данные")
            or gd.read_spreadsheet_values_from_sheet(file_id, "данные")
            or []
        )
        directory_names = parse_persons_directory(dir_rows)
        if directory_names:
            for n in directory_names:
                resolver.resolve(n)
            print(f"    directory: {len(directory_names)} persons")

        tx_rows, parse_warns = parse_transactions_from_rows(rows)
        all_warnings.extend(f"#{bid} «{name}» — {w}" for w in parse_warns)

        created_at = _bill_created_at(bill)
        bill_v2, warns = make_bill_v2(bill, tx_rows, resolver, created_at)
        all_warnings.extend(f"#{bid} «{name}» — {w}" for w in warns)
        new_bills_v2.append(bill_v2)
        print(
            f"    → BillV2: {len(bill_v2['transactions'])} tx, "
            f"{len(bill_v2['participants'])} participants, "
            f"created_at={created_at.date().isoformat()}"
        )

    print(f"\n=== Payments ({len(payments)}) ===")
    for p in payments:
        pv2, warns = make_payment_v2(p, resolver)
        all_warnings.extend(f"payment — {w}" for w in warns)
        if pv2 is not None:
            new_payments_v2.append(pv2)

    print(f"  → {len(new_payments_v2)} BillPaymentV2 (status=confirmed, bill_ids=[])")

    print(f"\n=== DetailsInfo ({len(details_infos)}) ===")
    n_desc = apply_details_infos(details_infos, resolver)
    print(f"  → {n_desc} BillPerson.description set")

    print(f"\n=== Persons ===")
    print(f"  total bill_persons after migration: {len(resolver.bill_persons)}")
    print(f"  newly created during migration: {resolver.created_count}")
    if resolver.matched_to_user:
        sample = ", ".join(f"{n}→{d}" for n, d in resolver.matched_to_user[:8])
        print(f"  matched-to-user (first 8): {sample}")

    if all_warnings:
        print(f"\n=== Warnings ({len(all_warnings)}) ===")
        for w in all_warnings[:50]:
            print(f"  {w}")
        if len(all_warnings) > 50:
            print(f"  ... and {len(all_warnings) - 50} more")

    if skipped:
        print(f"\n=== Skipped bills ({len(skipped)}) ===")
        for bid, name, reason in skipped:
            print(f"  #{bid} «{name}» — {reason}")

    print(f"\n=== Summary ===")
    print(f"  Would create: {len(new_bills_v2)} bills_v2")
    print(f"  Would create: {sum(len(b['transactions']) for b in new_bills_v2)} transactions")
    print(f"  Would create: {len(new_payments_v2)} bill_payments_v2")
    print(f"  Would create: {resolver.created_count} bill_persons")
    print(f"  Would update: {n_desc} bill_persons (description)")

    if not apply:
        print("\nDRY RUN — re-run with --apply to commit.")
        return 0

    backup = db_path.with_suffix(db_path.suffix + ".bak.pre_v2_migration")
    print(f"\nWriting backup to {backup}")
    shutil.copy(db_path, backup)

    db["bill_persons"] = resolver.bill_persons
    db["bills_v2"] = list(db.get("bills_v2", [])) + new_bills_v2
    db["bill_payments_v2"] = list(db.get("bill_payments_v2", [])) + new_payments_v2

    db_path.write_text(
        json.dumps(db, sort_keys=True, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"WROTE {db_path}")
    print(
        "Done. Inspect with `git diff` (or compare against backup) and run "
        "`./venv/bin/python -m pytest tests/` to confirm models still parse."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="db.json", help="path to db.json (default: db.json)")
    p.add_argument("--apply", action="store_true", help="actually write (default is dry-run)")
    p.add_argument(
        "--force", action="store_true",
        help="proceed even if bills_v2/bill_payments_v2 already non-empty",
    )
    args = p.parse_args(argv)

    return run_migration(Path(args.db), apply=args.apply, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())

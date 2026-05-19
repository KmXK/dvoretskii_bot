#!/usr/bin/env python3
"""Admin CLI for dvoretskii_bot feature requests.

Usage:
    python scripts/api_admin.py list
    python scripts/api_admin.py list --status open
    python scripts/api_admin.py update 5 --status done
    python scripts/api_admin.py update 5 --status in_progress --priority 2
    python scripts/api_admin.py update 5 --note "some note"

Requires in .env: PROD_BOT_TOKEN (прод), ADMIN_USER_ID
"""

import argparse
import hashlib
import hmac
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def _load_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


_load_env()

BASE_URL = (os.environ.get("PROD_API_URL") or "").rstrip("/")
_BOT_TOKEN = os.environ.get("PROD_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
_ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0") or "0")

STATUS_NAMES = {0: "open", 1: "done", 2: "denied", 3: "in_progress", 4: "testing"}
STATUS_VALUES = {v: k for k, v in STATUS_NAMES.items()}
STATUS_EMOJI = {
    "open": "🔵",
    "in_progress": "🟡",
    "testing": "🟠",
    "done": "✅",
    "denied": "❌",
}


def _make_session_token() -> str:
    payload = f"{_ADMIN_USER_ID}:{int(time.time())}"
    sig = hmac.new(_BOT_TOKEN.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _api(method: str, path: str, body=None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Cookie": f"dvoretskii_sid={_make_session_token()}",
            "Origin": BASE_URL,
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def _fmt(fr: dict) -> str:
    status_key = STATUS_NAMES.get(fr.get("status", 0), "open")
    emoji = STATUS_EMOJI.get(status_key, "?")
    votes = len(fr.get("votes", []))
    priority = fr.get("priority", 5)
    text = fr["text"]
    if len(text) > 80:
        text = text[:79] + "…"
    return f"#{fr['id']:>3} {emoji} p={priority} 👍{votes}  {text}"


def cmd_list(args) -> None:
    items = _api("GET", "/api/feature-requests")
    if args.status:
        items = [x for x in items if STATUS_NAMES.get(x.get("status", 0), "open") == args.status]
    items.sort(key=lambda x: (-x.get("priority", 5), x.get("id", 0)))
    for fr in items:
        print(_fmt(fr))
    print(f"\nTotal: {len(items)}")


def cmd_update(args) -> None:
    body = {}
    if args.status:
        body["status"] = STATUS_VALUES[args.status]
    if args.priority is not None:
        body["priority"] = args.priority
    if args.note:
        body["note"] = args.note
    if not body:
        print("Nothing to update. Use --status, --priority, or --note.", file=sys.stderr)
        sys.exit(1)
    fr = _api("PATCH", f"/api/feature-requests/{args.id}", body)
    print(f"Updated: {_fmt(fr)}")


def main() -> None:
    if not BASE_URL:
        print("Error: PROD_API_URL not set in .env", file=sys.stderr)
        sys.exit(1)
    if not _BOT_TOKEN:
        print("Error: PROD_BOT_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)
    if not _ADMIN_USER_ID:
        print("Error: ADMIN_USER_ID not set in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Feature requests admin CLI")
    subs = parser.add_subparsers(dest="cmd", required=True)

    p_list = subs.add_parser("list", help="List feature requests")
    p_list.add_argument(
        "--status",
        choices=list(STATUS_VALUES),
        help="Filter by status",
    )
    p_list.set_defaults(func=cmd_list)

    p_update = subs.add_parser("update", help="Update a feature request")
    p_update.add_argument("id", type=int, help="Feature request ID")
    p_update.add_argument("--status", choices=list(STATUS_VALUES), help="New status")
    p_update.add_argument("--priority", type=int, help="New priority (1=highest)")
    p_update.add_argument("--note", help="Add a note")
    p_update.set_defaults(func=cmd_update)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

---
name: botmetrics
description: Query dvoretskii_bot production metrics (Prometheus/VictoriaMetrics) through the bot's admin API. Use when the user asks about metrics, traffic, message/handler/download counts, per-chat or per-user activity, or wants a PromQL query run against prod ("сколько сообщений", "посмотри метрики", "график по хендлерам", "how many downloads"). Optional args: a raw PromQL expression, or a metric name to inspect.
---

# Bot metrics (Prometheus → VictoriaMetrics → bot API)

The bot exposes Prometheus metrics on `:9090` (`steward/metrics/`, enabled via
`METRICS_ENABLED=true`). VictoriaMetrics scrapes them every 15s and keeps 18
months.

VictoriaMetrics is **only reachable inside the prod docker network** — there is
no public route and no SSH for it. We query through the bot's admin-only proxy
endpoint `/api/metrics/vm/*` (`steward/api/metrics_explorer.py`,
`handle_metrics_vm_proxy`), authenticated with a signed session cookie built
from the bot token (same scheme as `scripts/api_admin.py`).

## Required `.env` data (what another dev must add)

The query script reads these from the project `.env` (gitignored — never commit
real values). Without them the skill cannot run:

```sh
PROD_API_URL=https://tg.kmxk.ru   # prod webapp base URL
PROD_BOT_TOKEN=<token>            # prod bot token (falls back to TELEGRAM_BOT_TOKEN)
ADMIN_USER_ID=<telegram id>       # must be a bot admin (repo.db.admin_ids)
```

These are the same values `scripts/api_admin.py` uses. If a query fails with
HTTP 401, the token is wrong; with 403, the user id is not a bot admin; if
`.env not found`, you're not in the project root.

## How to query

Use `scripts/vmq.sh` (bash). Output is raw JSON from the Prometheus HTTP API.

```sh
bash scripts/vmq.sh --list                # all metric names currently stored
bash scripts/vmq.sh --labels <metric>     # every label set (series) for a metric
bash scripts/vmq.sh '<promql>'            # instant query
bash scripts/vmq.sh --range '<promql>' [STEP_SEC] [DURATION_SEC]
                                          # range query, defaults: step 60, last 3600s (1h)
```

## Metrics emitted by the bot

Run `--list` for the live set; counters also have a `_created` twin (ignore it).
As of writing:

| Metric | Labels | Meaning |
|---|---|---|
| `bot_messages_total` | `action_type` (chat/callback/reaction/message_edited), `chat_id`, `chat_name`, `user_id`, `user_name` | incoming updates |
| `bot_handler_calls_total` | per-handler labels | feature handler invocations |
| `bot_downloads_total` | — | video downloads |
| `bot_curse_words_total` | — | detected curse words |
| `bot_curse_punishment_done_total` | — | curse punishments applied |

Plus standard `process_*` / `python_*` / `scrape_*` / `up` from the client.

## Example PromQL

```sh
# Is the bot scrape target alive? (1 = up)
bash scripts/vmq.sh 'up'

# Total messages across everything
bash scripts/vmq.sh 'sum(bot_messages_total)'

# Messages per chat, busiest first
bash scripts/vmq.sh 'sort_desc(sum by (chat_name) (bot_messages_total))'

# Messages per action type
bash scripts/vmq.sh 'sum by (action_type) (bot_messages_total)'

# Message rate per chat over the last 5m
bash scripts/vmq.sh 'sum by (chat_name) (rate(bot_messages_total[5m]))'

# Handler calls, busiest handlers
bash scripts/vmq.sh 'sort_desc(sum by (handler) (bot_handler_calls_total))'

# Memory of the bot process
bash scripts/vmq.sh 'process_resident_memory_bytes{job="bot"}'

# Messages over the last 6h, 5m step (for a time series / graph)
bash scripts/vmq.sh --range 'sum(rate(bot_messages_total[5m]))' 300 21600
```

## Reading the output

The JSON shape is standard Prometheus:
- instant: `data.result[].value = [timestamp, "value"]`
- range: `data.result[].values = [[ts,"v"], ...]`
- `--list`: `data` is a flat array of names
- `--labels`: `data` is an array of label-set objects (series)

When answering the user, pull out the numbers and summarize — don't dump raw JSON
unless they ask. Counters are cumulative; use `rate()`/`increase()` for "how many
recently", and `sum by (...)` to aggregate away `user_id`/`chat_id` cardinality.

## What NOT to do

- This is **read-only**. The proxy only allows GET on `query`, `query_range`,
  `series`, `labels`, `label/.../values`. Never try to POST or write anything.
- Don't put credentials on the command line or in committed files — they live in
  `.env` only.
- Metric names/labels evolve; trust `--list`/`--labels` over this table, and the
  source in `steward/` over both.

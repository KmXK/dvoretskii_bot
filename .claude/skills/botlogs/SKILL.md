---
name: botlogs
description: Fetch dvoretskii_bot logs from Yandex Cloud Logging. Use when the user asks to look at the bot's logs ("что в логах", "посмотри логи", "проверь логи бота", "почему упало"), or when debugging a runtime issue would benefit from production logs. Optional args (free-form, in any order or language): time range (e.g. `30m`, `1h`, `2h`, `1d`), keyword to grep messages, severity (`error` / `warning` / `info`), or a raw `yc` filter expression starting with `level` / `message`.
---

# Bot logs (Yandex Cloud Logging)

The bot writes logs to Yandex Cloud Logging.

- Folder: `b1gvlnbo6ntffr5rbgbc`
- Log group: `e23ldb9rgcmpc511s7sh`
- UI: https://console.yandex.cloud/folders/b1gvlnbo6ntffr5rbgbc/logging/group/e23ldb9rgcmpc511s7sh/logs

## Prerequisite

The `yc` CLI must be installed and authenticated:

```bash
curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash
yc init
```

If `yc` is missing when this skill runs (`command not found: yc`), stop and tell the user the install command above. Don't try to fall back to the REST API — it requires JWT signing or OAuth dance and is not worth it.

## How to fetch logs

Resolve the binary first (the installer doesn't always patch `$PATH` for non-login shells):

```bash
YC=$(command -v yc || echo "$HOME/yandex-cloud/bin/yc")
```

If `$YC` doesn't exist, stop and tell the user to run the install command above.

Then:

```bash
"$YC" logging read \
  --group-id e23ldb9rgcmpc511s7sh \
  --since "$SINCE" \
  --limit "$LIMIT" \
  --filter "$FILTER" \
  --format json
```

`--format json` returns one JSON object per line (NDJSON) with at least: `timestamp`, `level`, `message`, optionally `json_payload`.

### Defaults

When called with no args:
- `SINCE = 30m`
- `LIMIT = 300`
- `FILTER = NOT message:"getUpdates"` — `getUpdates` polling is ~99% of log volume; suppress it unless the user explicitly asks for it.

### Parsing the user's args

The skill receives free-form text. Walk the words and classify each:

| Token shape | Action |
|---|---|
| `^\d+[smhd]$` (e.g. `30m`, `2h`, `1d`) | set `SINCE` |
| `^\d+$` and looks like a count (e.g. `500`) | set `LIMIT` |
| `error`, `errors`, `ошибки` | append `level >= ERROR` to FILTER |
| `warning`, `warn`, `варн`, `предупрежд*` | append `level >= WARN` to FILTER |
| `info` | append `level >= INFO` to FILTER |
| `debug` | append `level >= DEBUG` to FILTER |
| starts with `message:` / `level` / `json_payload.` | append verbatim to FILTER (raw `yc` filter syntax) |
| anything else (a keyword, possibly multi-word in quotes) | append `message:"<word>"` to FILTER |

Combine FILTER clauses with ` AND `. Always keep `NOT message:"getUpdates"` unless the user typed `getUpdates`, `polling`, `weall logs`, `+getupdates`, or similar.

`yc` filter language — see https://yandex.cloud/ru/docs/logging/concepts/filter — supports `=`, `!=`, `<`, `>`, `<=`, `>=`, `:` (substring), `IN`, `NOT IN`, `AND`, `OR`, `NOT`, parentheses, double-quoted string literals.

### Examples

| User input | Resulting flags |
|---|---|
| (empty) | `--since 30m --limit 300 --filter 'NOT message:"getUpdates"'` |
| `1h VLM` | `--since 1h --filter 'NOT message:"getUpdates" AND message:"VLM"'` |
| `30m error` | `--since 30m --filter 'NOT message:"getUpdates" AND level >= ERROR'` |
| `2h yandex stt error` | `--since 2h --filter 'NOT message:"getUpdates" AND message:"yandex" AND message:"stt" AND level >= ERROR'` |
| `Не удалось` | `--since 30m --filter 'NOT message:"getUpdates" AND message:"Не удалось"'` |

## Reading the output

Each JSON line typically has:

```json
{"timestamp":"2026-05-02T14:50:50.228Z","level":"INFO","message":"VLM skipped: AI_MODEL_VLM not set"}
```

Some entries have structured `json_payload` instead of `message` — fall back to it when `message` is empty.

## After fetching

1. If the user asked a specific question (e.g. "почему транскрипция упала"), answer it from the logs — quote actual timestamps and messages.
2. Otherwise, summarize: counts by level, the most recent error/warning with its full traceback if present, any obvious patterns or spikes.
3. Don't dump everything — pick what's relevant. If the user wants the raw dump, they can re-run with a tighter filter.
4. If `yc` returns 0 entries, say so explicitly and suggest widening the time range or relaxing the filter — don't fabricate.

## What NOT to do

- Don't run `yc logging read` without `--filter` on a wide time range — `getUpdates` will drown everything.
- Don't try to write to the log group, create resources, or modify YC config. This skill is read-only.
- Don't paginate beyond `LIMIT` automatically. If output is truncated, mention it and ask the user if they want more.

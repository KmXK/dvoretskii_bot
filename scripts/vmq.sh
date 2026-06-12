#!/usr/bin/env bash
#
# vmq.sh — query production metrics through the bot API (admin session cookie).
#
# The bot proxies PromQL to VictoriaMetrics via /api/metrics/vm/* (admin-only),
# so no SSH or direct VM access is needed.
#
# Reads from ../.env:
#   PROD_API_URL      https://tg.kmxk.ru   (required; no trailing slash needed)
#   PROD_BOT_TOKEN    prod bot token       (required; falls back to TELEGRAM_BOT_TOKEN)
#   ADMIN_USER_ID     your telegram id     (required; must be a bot admin)
#
# Usage:
#   ./vmq.sh '<promql>'                       instant query
#   ./vmq.sh --range '<promql>' [STEP] [DUR]  range query (default last 1h, step 60s)
#   ./vmq.sh --list                           list all metric names
#   ./vmq.sh --labels '<metric>'              list label sets for a metric
#
# Output is raw JSON from the Prometheus/VictoriaMetrics HTTP API.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: .env not found at $ENV_FILE" >&2
  exit 1
fi

while IFS='=' read -r key val; do
  case "$key" in
    PROD_API_URL|PROD_BOT_TOKEN|TELEGRAM_BOT_TOKEN|ADMIN_USER_ID)
      val="${val%$'\r'}"                 # strip trailing CR (Windows-edited .env)
      val="${val%\"}"; val="${val#\"}"   # strip surrounding quotes
      export "$key=$val"
      ;;
  esac
done < <(grep -E '^[[:space:]]*(PROD_API_URL|PROD_BOT_TOKEN|TELEGRAM_BOT_TOKEN|ADMIN_USER_ID)=' "$ENV_FILE" | sed 's/^[[:space:]]*//')

BOT_TOKEN="${PROD_BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
: "${PROD_API_URL:?PROD_API_URL is not set in .env}"
: "${BOT_TOKEN:?PROD_BOT_TOKEN (or TELEGRAM_BOT_TOKEN) is not set in .env}"
: "${ADMIN_USER_ID:?ADMIN_USER_ID is not set in .env}"
PROD_API_URL="${PROD_API_URL%/}"         # trim trailing slash

# Session cookie: "<user_id>:<ts>:<hmac-sha256(payload, bot_token)>" —
# same scheme as steward/api/auth.py make_session_token().
payload="${ADMIN_USER_ID}:$(date +%s)"
sig="$(printf '%s' "$payload" | openssl dgst -sha256 -hmac "$BOT_TOKEN" | awk '{print $NF}')"
COOKIE="dvoretskii_sid=${payload}:${sig}"

vm() { curl -fsS --max-time 30 -H "Cookie: ${COOKIE}" "${PROD_API_URL}/api/metrics/vm$1"; }

urlenc() {
  local s="$1" out="" c i
  for (( i=0; i<${#s}; i++ )); do
    c="${s:$i:1}"
    case "$c" in
      [a-zA-Z0-9._~-]) out+="$c" ;;
      *) printf -v c '%%%02X' "'$c"; out+="$c" ;;
    esac
  done
  printf '%s' "$out"
}

mode="${1:-}"
case "$mode" in
  --list)        vm "/label/__name__/values" ;;
  --labels)
    metric="${2:?usage: vmq.sh --labels <metric>}"
    vm "/series?match[]=$(urlenc "$metric")" ;;
  --range)
    q="${2:?usage: vmq.sh --range <promql> [step] [duration]}"
    step="${3:-60}"; dur="${4:-3600}"
    end="$(date +%s)"; start="$((end - dur))"
    vm "/query_range?query=$(urlenc "$q")&start=${start}&end=${end}&step=${step}" ;;
  "")
    echo "usage: vmq.sh '<promql>' | --range '<promql>' [step] [dur] | --list | --labels <metric>" >&2
    exit 1 ;;
  *) vm "/query?query=$(urlenc "$mode")" ;;
esac
echo

#!/usr/bin/env bash
#
# vmq.sh — query production metrics through the Grafana HTTP API (basic auth).
#
# Grafana proxies PromQL to its VictoriaMetrics datasource, so no SSH or direct
# VM access is needed — just the Grafana login you already use in the browser.
#
# Reads from ../.env:
#   GRAFANA_URL       https://grafana.tg.kmxk.ru   (required)
#   GRAFANA_USER      login                        (required)
#   GRAFANA_PASSWORD  password                     (required)
#   GRAFANA_DS_UID    datasource uid               (optional; auto-detected)
#
# Usage:
#   ./vmq.sh '<promql>'                       instant query
#   ./vmq.sh --range '<promql>' [STEP] [DUR]  range query (default last 1h, step 60s)
#   ./vmq.sh --list                           list all metric names
#   ./vmq.sh --labels '<metric>'              list label sets for a metric
#   ./vmq.sh --datasources                    list datasources (debug)
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
    GRAFANA_URL|GRAFANA_USER|GRAFANA_PASSWORD|GRAFANA_DS_UID)
      val="${val%$'\r'}"                 # strip trailing CR (Windows-edited .env)
      val="${val%\"}"; val="${val#\"}"   # strip surrounding quotes
      export "$key=$val"
      ;;
  esac
done < <(grep -E '^[[:space:]]*GRAFANA_' "$ENV_FILE" | sed 's/^[[:space:]]*//')

: "${GRAFANA_URL:?GRAFANA_URL is not set in .env}"
: "${GRAFANA_USER:?GRAFANA_USER is not set in .env}"
: "${GRAFANA_PASSWORD:?GRAFANA_PASSWORD is not set in .env}"
GRAFANA_URL="${GRAFANA_URL%/}"           # trim trailing slash

AUTH=(-u "${GRAFANA_USER}:${GRAFANA_PASSWORD}")
CURL=(curl -fsS --max-time 30 "${AUTH[@]}")

graf() { "${CURL[@]}" "${GRAFANA_URL}$1"; }

# Find the prometheus-type datasource uid once, unless pinned in .env.
# Pass the parser via -c so curl's piped output stays on python's stdin.
resolve_ds() {
  [[ -n "${GRAFANA_DS_UID:-}" ]] && { printf '%s' "$GRAFANA_DS_UID"; return; }
  graf "/api/datasources" | "$PY" -c 'import json,sys
data=json.load(sys.stdin)
uid=next((d["uid"] for d in data if d.get("type")=="prometheus"), None)
print(uid) if uid else sys.exit("no prometheus datasource found")'
}

# Pick a python interpreter (only used to parse the datasource list).
PY="$(command -v python3 || command -v python || true)"
[[ -z "$PY" ]] && { echo "error: python not found (needed to parse datasource list)" >&2; exit 1; }

vm() {
  local uid; uid="$(resolve_ds)"
  graf "/api/datasources/proxy/uid/${uid}$1"
}

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
  --datasources) graf "/api/datasources" ;;
  --list)        vm "/api/v1/label/__name__/values" ;;
  --labels)
    metric="${2:?usage: vmq.sh --labels <metric>}"
    vm "/api/v1/series?match[]=$(urlenc "$metric")" ;;
  --range)
    q="${2:?usage: vmq.sh --range <promql> [step] [duration]}"
    step="${3:-60}"; dur="${4:-3600}"
    end="$(date +%s)"; start="$((end - dur))"
    vm "/api/v1/query_range?query=$(urlenc "$q")&start=${start}&end=${end}&step=${step}" ;;
  "")
    echo "usage: vmq.sh '<promql>' | --range '<promql>' [step] [dur] | --list | --labels <metric> | --datasources" >&2
    exit 1 ;;
  *) vm "/api/v1/query?query=$(urlenc "$mode")" ;;
esac
echo

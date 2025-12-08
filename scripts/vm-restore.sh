#!/bin/bash

# VictoriaMetrics restore from S3 backup
#
# Required env vars:
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#
# Optional:
#   AWS_REGION (default: ru-central1)
#   S3_ENDPOINT (for S3-compatible storage like Yandex Cloud, MinIO)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"
if [[ -f "$ENV_FILE" ]]; then
  eval "$(grep -E '^YC_S3_' "$ENV_FILE")"
fi

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-$YC_S3_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-$YC_S3_KEY_SECRET}"

: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID or YC_S3_KEY_ID is not set}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY or YC_S3_KEY_SECRET is not set}"

BACKUP_SRC="${1:?Usage: $0 <s3://bucket/path/to/backup> [storage_target]}"
STORAGE_TARGET="${2:-dvoretskii_bot_victoriametrics_data}"

echo "Restoring from: $BACKUP_SRC"
echo "Target: $STORAGE_TARGET"

if [[ "$STORAGE_TARGET" == */* ]]; then
  VOLUME_ARG="$(realpath "$STORAGE_TARGET"):/data"
else
  VOLUME_ARG="$STORAGE_TARGET:/data"
fi

docker run --rm \
  -v "$VOLUME_ARG" \
  -e AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY \
  victoriametrics/vmrestore:latest \
  -customS3Endpoint="${S3_ENDPOINT:-https://storage.yandexcloud.net}" \
  -src="$BACKUP_SRC" \
  -storageDataPath=/data

echo "Done."

# Examples:
#   Into named volume (default):
#     ./vm-restore.sh s3://bucket/vm-backup
#     ./vm-restore.sh s3://bucket/vm-backup my_volume_name
#
#   Into local directory:
#     ./vm-restore.sh s3://bucket/vm-backup ./victoria-metrics-data
#     ./vm-restore.sh s3://bucket/vm-backup /var/lib/victoria-metrics


#!/bin/bash

# VictoriaMetrics restore from S3 backup
#
# Required env vars:
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#
# Optional:
#   AWS_REGION (default: us-east-1)
#   S3_ENDPOINT (for S3-compatible storage like Yandex Cloud, MinIO)

set -e

BACKUP_SRC="${1:?Usage: $0 <s3://bucket/path/to/backup> [storage_data_path]}"
STORAGE_PATH="${2:-./victoria-metrics-data}"

echo "Restoring from: $BACKUP_SRC"
echo "Target path: $STORAGE_PATH"

# Docker-based restore
docker run --rm \
  -v "$(realpath "$STORAGE_PATH"):/data" \
  -e AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY \
  ${AWS_REGION:+-e AWS_REGION} \
  ${S3_ENDPOINT:+-e customS3Endpoint="$S3_ENDPOINT"} \
  victoriametrics/vmrestore:latest \
  -src="$BACKUP_SRC" \
  -storageDataPath=/data

echo "Done. Start VM with:"
echo "  docker run -v $(realpath "$STORAGE_PATH"):/victoria-metrics-data victoriametrics/victoria-metrics -storageDataPath=/victoria-metrics-data"

# Examples:
#   ./vm-restore.sh s3://my-bucket/vm-backups/2024-01-01
#   ./vm-restore.sh s3://my-bucket/vm-backups/2024-01-01 /var/lib/victoria-metrics
#
# For Yandex Cloud S3:
#   S3_ENDPOINT=https://storage.yandexcloud.net ./vm-restore.sh s3://bucket/backup


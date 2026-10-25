#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

docker_command=(docker)
if [[ $(id -u) -ne 0 ]]; then
  docker_command=(sudo -n docker)
fi
compose=("${docker_command[@]}" compose --parallel 1 --file compose.yaml)

"${compose[@]}" config --quiet
# Build first so running containers stay available if the build fails.
"${compose[@]}" build bot caddy
"${compose[@]}" pull --ignore-buildable
"${compose[@]}" up -d --wait --wait-timeout 240
"${compose[@]}" ps

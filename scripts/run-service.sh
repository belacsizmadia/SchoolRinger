#!/usr/bin/env bash
set -euo pipefail

app_dir=${SCHOOLRINGER_APP_DIR:-/opt/schoolringer}
data_dir=${SCHOOLRINGER_DATA_DIR:-/var/lib/schoolringer}
web_host=${SCHOOLRINGER_WEB_HOST:-0.0.0.0}
web_port=${SCHOOLRINGER_WEB_PORT:-5000}
media_port=${SCHOOLRINGER_MEDIA_PORT:-8080}
host_ip=${SCHOOLRINGER_HOST_IP:-}

args=(
  "$app_dir/scheduler_app.py"
  --host "$web_host"
  --port "$web_port"
  --media-dir "$data_dir/media"
  --config "$data_dir/data/schedules.json"
  --cast-media-port "$media_port"
)

if [[ -n "$host_ip" ]]; then
  args+=(--host-ip "$host_ip")
fi

exec "$app_dir/.venv/bin/python" "${args[@]}"

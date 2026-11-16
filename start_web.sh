#!/usr/bin/env bash
# 线上/沙箱启动脚本：强制使用 SQLite，初始化演示数据，监听平台注入的 PORT。
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python)"

export USE_SQLITE=1
export DJANGO_DEBUG="${DJANGO_DEBUG:-1}"

"$PY" manage.py migrate --noinput
"$PY" manage.py init_demo_data

exec "$PY" manage.py runserver "0.0.0.0:${PORT:-8000}" --noreload

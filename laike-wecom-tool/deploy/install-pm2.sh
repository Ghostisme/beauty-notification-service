#!/usr/bin/env bash
# Run as the account that owns the existing PM2 process list.
# Installs this tool only; site routing is switched separately after validation.
set -euo pipefail
umask 0077

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
APP_NAME=laike-wecom-tool
LAIKE_PYTHON="${LAIKE_PYTHON:-python3.12}"

for dependency in "$LAIKE_PYTHON" node pm2 curl; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        echo "缺少依赖：$dependency。请先按域名迁移说明安装，再运行本脚本。" >&2
        exit 1
    fi
done

"$LAIKE_PYTHON" - <<'PY'
import json
import socket
import sqlite3
import sys
from pathlib import Path

if sys.version_info < (3, 12):
    raise SystemExit("请使用 Python 3.12 或更高版本；当前锁定依赖已在 Python 3.12 验证。")
data = Path("data")
if (data / ".demo-mode").exists():
    raise SystemExit("data 是演示目录，不能作为正式实例部署。")
database, key = data / "tool.db", data / ".master-key"
if database.exists() != key.exists():
    raise SystemExit("数据库与加密密钥不成对，请恢复同一份迁移备份后重试。")
if database.exists():
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        for section, field in (("scheduler", "enabled"), ("notifications", "delivery_enabled")):
            row = connection.execute("SELECT value FROM settings WHERE key=?", (section,)).fetchone()
            if row and json.loads(row[0]).get(field):
                raise SystemExit("迁移备份中的自动同步或自动发送仍开启。请先暂停本机任务，重新备份后迁移。")
        active = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE status IN ('sending','waiting_receipt')"
        ).fetchone()[0]
        if active:
            raise SystemExit("迁移备份存在发送中或等待回执的任务，请先核实其结果再迁移。")
    finally:
        connection.close()
try:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 8790))
except OSError:
    raise SystemExit("127.0.0.1:8790 已被占用，请先确认运行实例；本脚本不会停止占用进程。")
PY

if pm2 describe "$APP_NAME" >/dev/null 2>&1; then
    echo "PM2 已存在 $APP_NAME，请使用迁移说明中的更新流程，不重复安装。" >&2
    exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
    "$LAIKE_PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock
mkdir -p data
chmod 700 data
.venv/bin/python run.py --init-only
.venv/bin/python manage.py check
pm2 start deploy/ecosystem.config.js --only "$APP_NAME"

for attempt in {1..10}; do
    if curl --fail --silent --max-time 5 http://127.0.0.1:8790/health |
        .venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("status")=="ok" and d.get("version")=="1.0.0" else 1)' 2>/dev/null; then
        pm2 save
        echo "新工具已由 PM2 启动，数据库和本机健康检查通过。"
        echo "下一步：按 docs/notification.hongquanquan.cn迁移.md 修改现有 HTTPS 站点代理。"
        exit 0
    fi
    sleep 1
done

pm2 stop "$APP_NAME" >/dev/null 2>&1 || true
echo "新工具未通过健康检查，已停止本脚本创建的进程。请查看 pm2 logs $APP_NAME --lines 60 --nostream。" >&2
exit 1

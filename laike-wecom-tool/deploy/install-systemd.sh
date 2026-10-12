#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "$PWD" != "/opt/laike-wecom-tool" ]]; then
  echo "请把程序放到 /opt/laike-wecom-tool 后运行此安装脚本。"
  exit 1
fi
if [[ "$EUID" != 0 ]]; then echo "请使用 sudo bash deploy/install-systemd.sh"; exit 1; fi
if ! command -v python3 >/dev/null; then echo "请先安装 Python 3.12 和 python3-venv"; exit 1; fi
if ! id laike-tool >/dev/null 2>&1; then useradd --system --home-dir /opt/laike-wecom-tool --shell /usr/sbin/nologin laike-tool; fi
python3 -m venv .venv
.venv/bin/pip install --disable-pip-version-check -r requirements.lock
install -d -m 700 -o laike-tool -g laike-tool data
chown laike-tool:laike-tool data
install -m 644 deploy/laike-tool.service deploy/laike-backup.service deploy/laike-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now laike-tool.service laike-backup.timer
echo "已安装后台服务及每日备份。初始密码在 data/.bootstrap-password；下一步配置 HTTPS 反向代理。"

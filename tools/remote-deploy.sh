#!/usr/bin/env bash
# ============================================================================
# 服务器端部署（在服务器上跑）—— 解压发布包 → 重建容器 → 自检
#
# 用法：
#   cd /opt/beauty-notification-service
#   bash tools/remote-deploy.sh /tmp/dylk-20260920-170000-37204a9.tar.gz
#
# 做四件事：
#   1) 备份 config.json / data/admin.db / .admin_token（带时间戳，放 backups/）
#   2) 解压发布包覆盖代码（这些密钥与数据不在包里，不受影响）
#   3) 补全新版本新增的配置项（只补缺失的，不动你的密钥和已有值）
#   4) docker compose up -d --build 重建容器 + 健康检查
#
# 全程不访问 GitHub。
# ============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/beauty-notification-service}"
PKG="${1:-}"
STAMP="$(date +%Y%m%d-%H%M%S)"

if [ -z "$PKG" ]; then
  echo "用法: bash tools/remote-deploy.sh <发布包路径>"
  echo "例如: bash tools/remote-deploy.sh /tmp/dylk-20260920-170000-37204a9.tar.gz"
  exit 1
fi
[ -f "$PKG" ] || { echo "✘ 找不到发布包: $PKG"; exit 1; }
[ -d "$APP_DIR" ] || { echo "✘ 找不到项目目录: $APP_DIR（可用 APP_DIR=... 指定）"; exit 1; }

cd "$APP_DIR"
echo "==> [1/4] 备份配置与数据"
mkdir -p backups
if [ -f config.json ]; then cp -a config.json "backups/config-$STAMP.json"; echo "    config.json   -> backups/config-$STAMP.json"; fi
if [ -f data/admin.db ]; then cp -a data/admin.db "backups/admin-$STAMP.db"; echo "    data/admin.db -> backups/admin-$STAMP.db"; fi
if [ -f .admin_token ]; then cp -a .admin_token "backups/admin_token-$STAMP"; echo "    .admin_token  -> backups/admin_token-$STAMP"; fi

echo "==> [2/4] 解压发布包（覆盖代码，不动密钥/数据）"
tar xzf "$PKG" -C "$APP_DIR" --strip-components=1
mkdir -p data/incoming data/processed state logs web
echo "    已覆盖，包内文件数：$(tar tzf "$PKG" | wc -l)"

echo "==> [3/4] 补全新配置项（只补缺失的）"
if command -v python3 >/dev/null 2>&1; then
  python3 tools/patch-config.py || echo "    ⚠ 配置补丁未成功，可手动检查 config.json"
else
  echo "    宿主机没有 python3，跳过（容器内仍能正常跑；也可手动补 config.json）"
fi

echo "==> [4/4] 重建并启动容器"
TOKEN="${ADMIN_TOKEN:-$(cat .admin_token 2>/dev/null || true)}"
if [ -z "$TOKEN" ]; then
  TOKEN="$(openssl rand -hex 24)"
  printf '%s' "$TOKEN" > .admin_token
  chmod 600 .admin_token
  echo "    生成了新的 ADMIN_TOKEN: $TOKEN"
fi
printf 'ADMIN_TOKEN=%s\n' "$TOKEN" > .env
chmod 600 .env
ADMIN_TOKEN="$TOKEN" docker compose up -d --build

echo -n "    健康检查: "
for i in 1 2 3 4 5 6; do
  sleep 3
  R="$(curl -s -m 5 http://127.0.0.1:8787/api/health || true)"
  if echo "$R" | grep -q '"ok"'; then echo "OK  $R"; break; fi
  if [ "$i" = 6 ]; then echo "FAIL"; docker compose logs --tail 30 dylk-admin || true; fi
done

cat <<EOF

────────────────────────────────────────────────────────────────
✔ 部署完成（备份在 $APP_DIR/backups/）

  后台地址:  https://notification.hongquanquan.cn
  访问令牌:  $APP_DIR/.admin_token
  改配置后:  docker compose restart      （config.json 是挂载卷，改完重启即生效）
  看日志:    docker compose logs -f dylk-admin

  云端中继（如果用它，见「操作手册」第 8 章）:
    cd $APP_DIR/deploy/wechat
    ADMIN_TOKEN=\$(cat ../../.admin_token) docker compose up -d --build
────────────────────────────────────────────────────────────────
EOF

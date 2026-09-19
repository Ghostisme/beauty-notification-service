#!/usr/bin/env bash
# 一键部署脚本 (Ubuntu 24.04, 全局 nginx + Docker 后端)
# 用法: 在服务器上项目目录内执行  sudo bash deploy.sh
#       可选: HTTPS=1 sudo bash deploy.sh   (同时用 certbot 配证书)
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="notification.hongquanquan.cn"
PORT=8787
REPO="https://github.com/Ghostisme/beauty-notification-service.git"
OLD_DIR="/var/www/beauty-notification"

echo "==> [0/6] 清理旧服务(pm2 nodejs)"
if command -v pm2 >/dev/null 2>&1; then
  pm2 delete all >/dev/null 2>&1 || true
  pm2 save --force >/dev/null 2>&1 || true
  pm2 kill >/dev/null 2>&1 || true
  echo "    pm2 服务已停止并清除"
else
  echo "    未安装 pm2, 跳过"
fi

echo "==> [0.5/6] 同步代码(git)"
if [ "$APP_DIR" != "/opt/beauty-notification-service" ]; then
  if [ -d /opt/beauty-notification-service/.git ]; then
    git -C /opt/beauty-notification-service pull --ff-only || true
    APP_DIR=/opt/beauty-notification-service
  elif [ "$APP_DIR" = "$OLD_DIR" ] || [ ! -d "$APP_DIR/.git" ]; then
    git clone "$REPO" /opt/beauty-notification-service
    APP_DIR=/opt/beauty-notification-service
  fi
fi
cd "$APP_DIR"

echo "==> [1/6] 检查 Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "    未安装 Docker, 优先走阿里云镜像安装(国内网络)..."
  if ! curl -fsSL https://get.docker.com -o /tmp/getdocker.sh; then
    echo "    get.docker.com 不可达, 改用 apt 安装..."
    apt-get update -y
    apt-get install -y docker.io docker-compose-v2
  else
    bash /tmp/getdocker.sh --mirror Aliyun
  fi
  systemctl enable --now docker
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "    缺少 docker compose 插件, 尝试 apt 安装 docker-compose-v2..."
  apt-get update -y && apt-get install -y docker-compose-v2
fi

# Docker Hub 拉镜像加速(国内网络): 配置镜像源
if ! grep -q "registry-mirrors" /etc/docker/daemon.json 2>/dev/null; then
  mkdir -p /etc/docker
  cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io",
    "https://dockerproxy.net"
  ]
}
EOF
  systemctl restart docker 2>/dev/null || true
  echo "    已配置 Docker Hub 镜像加速"
fi

echo "==> [2/6] 准备目录与配置"
mkdir -p data/incoming data/processed state logs web
if [ ! -f config.json ]; then
  cp config.json.example config.json
  echo "    config.json 不存在, 已从 config.json.example 创建(密钥留空, 可之后在管理后台页面填写)"
fi
chmod 600 config.json || true

echo "==> [3/6] ADMIN_TOKEN"
if [ -z "${ADMIN_TOKEN:-}" ]; then
  if [ -f .admin_token ]; then
    ADMIN_TOKEN="$(cat .admin_token)"
  else
    ADMIN_TOKEN="$(openssl rand -hex 24)"
    printf '%s' "$ADMIN_TOKEN" > .admin_token
    chmod 600 .admin_token
  fi
fi
export ADMIN_TOKEN
# 写进 .env(compose 自动读取), 保证以后手动 docker compose up 不再缺变量
printf 'ADMIN_TOKEN=%s\n' "$ADMIN_TOKEN" > .env
chmod 600 .env
echo "    ADMIN_TOKEN = $ADMIN_TOKEN"
echo "    (已保存到 $APP_DIR/.admin_token, 管理后台页面输入它登录)"

echo "==> [4/6] 构建并启动后端容器"
# 预拉取基础镜像: registry-1.docker.io 在国内常被 DNS 污染, 依次尝试镜像源, 成功后打回标准 tag
BASE_IMG="python:3.12-slim"
if ! docker image inspect "$BASE_IMG" >/dev/null 2>&1; then
  for m in docker.1ms.run docker.m.daocloud.io dockerproxy.net docker.aityp.com; do
    echo "    尝试从 $m 拉取 $BASE_IMG ..."
    if docker pull "$m/library/$BASE_IMG"; then
      docker tag "$m/library/$BASE_IMG" "$BASE_IMG"
      echo "    基础镜像就绪(经 $m)"
      break
    fi
  done
fi
if ! docker image inspect "$BASE_IMG" >/dev/null 2>&1; then
  echo "    所有镜像源均失败, 请手动配置你自己的阿里云镜像加速器后重跑:"
  echo "    登录 cr.console.aliyun.com -> 镜像加速器 -> 按提示写 /etc/docker/daemon.json"
  exit 1
fi
docker compose up -d --build

echo "==> [5/6] 配置全局 nginx (静态前端 + /api 反代)"
# 清理旧部署遗留的同域名配置(否则 server name 冲突, 新配置被忽略)
conflict="$(grep -rl "$DOMAIN" /etc/nginx/sites-enabled/ 2>/dev/null | grep -v "sites-enabled/$DOMAIN$")"
if [ -n "$conflict" ]; then
  echo "    移除冲突的旧 nginx 配置: $conflict"
  echo "$conflict" | xargs rm -f
fi
cat > /etc/nginx/sites-available/$DOMAIN <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    root $APP_DIR/web;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 120s;
    }
}
EOF
ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/$DOMAIN
nginx -t && systemctl reload nginx

echo "==> [6/6] 自检"
echo -n "  服务器出口IP(应 47.103.32.12): "; curl -s ifconfig.me || true; echo
echo -n "  后端健康: "
for i in 1 2 3 4 5; do
  sleep 2
  R="$(curl -s -m 5 http://127.0.0.1:$PORT/api/health || true)"
  if echo "$R" | grep -q '"ok"'; then echo "OK ($R)"; break; fi
  [ "$i" = 5 ] && { echo "FAIL"; echo "  --- 容器日志(最后20行) ---"; docker compose logs --tail 20 2>/dev/null || true; }
done
echo -n "  页面: "; curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/ 2>/dev/null || \
       curl -s -o /dev/null -w "%{http_code}" http://localhost/ ; echo

if [ "${HTTPS:-0}" = "1" ]; then
  echo "==> 配置 HTTPS (certbot)"
  apt-get update -y && apt-get install -y certbot python3-certbot-nginx
  certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m admin@hongquanquan.cn || \
    echo "    certbot 失败, 确认域名已解析到本机后重试: certbot --nginx -d $DOMAIN"
fi

cat <<EOF

============================================================
 部署完成
  访问:  http(或https)://$DOMAIN   登录令牌见 .admin_token
  后续改配置: 编辑 config.json -> docker compose restart
  查看日志:   docker compose logs -f
  拿到企微 Secret 后: 打开页面 -> 全局配置填入 secret 保存,
             或直接编辑 config.json 的 wecom.secret 后重启
============================================================
EOF

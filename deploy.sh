#!/bin/bash

# 一键部署脚本
# 用于在全新的 Ubuntu 服务器上快速部署系统

set -e  # 遇到错误立即退出

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 美容店来客通知系统 - 一键部署脚本"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then
  echo "❌ 请使用 root 用户运行此脚本"
  exit 1
fi

# 读取配置
read -p "请输入你的域名(例如: example.com): " DOMAIN
read -p "请输入数据库密码: " -s DB_PASSWORD
echo ""

echo "📦 步骤 1/8: 更新系统..."
apt-get update -qq
apt-get upgrade -y -qq

echo "📦 步骤 2/8: 安装 Node.js..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

echo "📦 步骤 3/8: 安装 MySQL..."
DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server
systemctl start mysql
systemctl enable mysql

echo "📦 步骤 4/8: 配置数据库..."
mysql -e "CREATE DATABASE IF NOT EXISTS beauty_notification CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -e "CREATE USER IF NOT EXISTS 'beauty_user'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';"
mysql -e "GRANT ALL PRIVILEGES ON beauty_notification.* TO 'beauty_user'@'localhost';"
mysql -e "FLUSH PRIVILEGES;"

echo "📦 步骤 5/8: 安装 PM2..."
npm install -g pm2

echo "📦 步骤 6/8: 安装 Nginx..."
apt-get install -y nginx
systemctl start nginx
systemctl enable nginx

echo "📦 步骤 7/8: 申请 SSL 证书..."
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos --register-unsafely-without-email

echo "📦 步骤 8/8: 配置 Nginx..."
cat > /etc/nginx/sites-available/beauty-notification <<EOF
server {
    listen 80;
    server_name ${DOMAIN};
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
    }
}
EOF

ln -sf /etc/nginx/sites-available/beauty-notification /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 服务器环境部署完成!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 下一步:"
echo "1. 上传项目代码到 /opt/beauty-notification-service"
echo "2. 配置 .env 文件"
echo "3. 运行: cd /opt/beauty-notification-service && npm install"
echo "4. 运行: pm2 start src/server.js --name beauty-notification"
echo ""
echo "🌐 你的域名: https://${DOMAIN}"
echo "💾 数据库已创建: beauty_notification"
echo "👤 数据库用户: beauty_user"
echo ""

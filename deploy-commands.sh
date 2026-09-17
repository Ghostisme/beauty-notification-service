#!/bin/bash

# ========================================
# 美容店来客通知系统 - 完整部署脚本
# 适用于全新的 Ubuntu/Debian ECS 服务器
# ========================================

echo "=========================================="
echo "开始部署美容店来客通知系统"
echo "=========================================="
echo ""

# 1. 更新系统
echo "📦 步骤 1/8: 更新系统包..."
apt update && apt upgrade -y

# 2. 安装 Node.js 18.x
echo ""
echo "📦 步骤 2/8: 安装 Node.js 18.x..."
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt install -y nodejs
echo "✅ Node.js 版本: $(node -v)"
echo "✅ NPM 版本: $(npm -v)"

# 3. 安装 PM2 进程管理器
echo ""
echo "📦 步骤 3/8: 安装 PM2..."
npm install -g pm2
echo "✅ PM2 版本: $(pm2 -v)"

# 4. 安装 Nginx
echo ""
echo "📦 步骤 4/8: 安装 Nginx..."
apt install -y nginx
systemctl enable nginx
systemctl start nginx
echo "✅ Nginx 已安装并启动"

# 5. 安装 Certbot (Let's Encrypt SSL 证书工具)
echo ""
echo "📦 步骤 5/8: 安装 Certbot..."
apt install -y certbot python3-certbot-nginx
echo "✅ Certbot 已安装"

# 6. 配置防火墙
echo ""
echo "🔥 步骤 6/8: 配置防火墙..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
echo "y" | ufw enable
echo "✅ 防火墙已配置"

# 7. 创建项目目录
echo ""
echo "📁 步骤 7/8: 创建项目目录..."
mkdir -p /var/www/beauty-notification-service
chown -R $USER:$USER /var/www/beauty-notification-service
echo "✅ 项目目录已创建: /var/www/beauty-notification-service"

# 8. 显示下一步操作
echo ""
echo "=========================================="
echo "✅ 基础环境安装完成!"
echo "=========================================="
echo ""
echo "📋 下一步操作:"
echo ""
echo "1. 上传代码到服务器:"
echo "   scp -r beauty-notification-service/* root@你的服务器IP:/var/www/beauty-notification-service/"
echo ""
echo "2. 或者使用 Git 克隆:"
echo "   cd /var/www/beauty-notification-service"
echo "   git clone <你的仓库地址> ."
echo ""
echo "3. 安装依赖:"
echo "   cd /var/www/beauty-notification-service"
echo "   npm install"
echo ""
echo "4. 配置 SSL 证书 (需要先解析域名到此服务器):"
echo "   certbot --nginx -d www.hongquanquan.cn -d hongquanquan.cn"
echo ""
echo "=========================================="

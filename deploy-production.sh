#!/bin/bash

# 美容店来客通知系统 - 生产环境部署脚本
# 使用 NVM + PM2 + Nginx

set -e

echo "========================================="
echo "美容店来客通知系统 - 生产环境部署"
echo "========================================="

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 项目配置
PROJECT_NAME="beauty-notification"
PROJECT_DIR="/var/www/beauty-notification"
NODE_VERSION="18"  # 推荐 Node.js 版本
NGINX_SITE_NAME="beauty-notification"
DOMAIN="your-domain.com"  # 修改为你的域名

# 检查是否为 root 或有 sudo 权限
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}请使用 sudo 运行此脚本${NC}"
    exit 1
fi

echo ""
echo "==> 步骤 1: 检查系统依赖"
echo ""

# 检查并安装 NVM
if [ ! -d "$HOME/.nvm" ]; then
    echo -e "${YELLOW}安装 NVM...${NC}"
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

    # 加载 NVM
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
else
    echo -e "${GREEN}✅ NVM 已安装${NC}"
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
fi

# 安装指定版本的 Node.js
echo ""
echo -e "${YELLOW}安装 Node.js ${NODE_VERSION}...${NC}"
nvm install $NODE_VERSION
nvm use $NODE_VERSION
nvm alias default $NODE_VERSION

echo -e "${GREEN}✅ Node.js 版本: $(node -v)${NC}"

# 安装 PM2
if ! command -v pm2 &> /dev/null; then
    echo ""
    echo -e "${YELLOW}安装 PM2...${NC}"
    npm install -g pm2
else
    echo -e "${GREEN}✅ PM2 已安装${NC}"
fi

# 检查 Nginx
if ! command -v nginx &> /dev/null; then
    echo ""
    echo -e "${YELLOW}安装 Nginx...${NC}"
    apt-get update
    apt-get install -y nginx
else
    echo -e "${GREEN}✅ Nginx 已安装${NC}"
fi

# 检查 MySQL
if ! command -v mysql &> /dev/null; then
    echo ""
    echo -e "${YELLOW}MySQL 未安装,请手动安装 MySQL${NC}"
    echo "sudo apt-get install mysql-server"
else
    echo -e "${GREEN}✅ MySQL 已安装${NC}"
fi

echo ""
echo "==> 步骤 2: 创建项目目录"
echo ""

# 创建项目目录
mkdir -p $PROJECT_DIR
mkdir -p /var/log/$PROJECT_NAME

echo -e "${GREEN}✅ 项目目录创建完成: $PROJECT_DIR${NC}"

echo ""
echo "==> 步骤 3: 复制项目文件"
echo ""

# 复制当前目录的文件到项目目录
CURRENT_DIR=$(pwd)
echo "从 $CURRENT_DIR 复制文件到 $PROJECT_DIR"

rsync -av --exclude 'node_modules' \
          --exclude '.git' \
          --exclude 'logs' \
          --exclude '.env' \
          $CURRENT_DIR/ $PROJECT_DIR/

echo -e "${GREEN}✅ 文件复制完成${NC}"

echo ""
echo "==> 步骤 4: 配置环境变量"
echo ""

# 检查 .env 文件
if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$CURRENT_DIR/.env" ]; then
        cp "$CURRENT_DIR/.env" "$PROJECT_DIR/.env"
        echo -e "${GREEN}✅ 已复制 .env 文件${NC}"
    else
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        echo -e "${YELLOW}⚠️  已创建 .env 文件,请编辑配置${NC}"
        echo "编辑文件: nano $PROJECT_DIR/.env"
        read -p "按回车键继续..."
    fi
else
    echo -e "${GREEN}✅ .env 文件已存在${NC}"
fi

echo ""
echo "==> 步骤 5: 安装项目依赖"
echo ""

cd $PROJECT_DIR
npm install --production

echo -e "${GREEN}✅ 依赖安装完成${NC}"

echo ""
echo "==> 步骤 6: 配置 Nginx"
echo ""

# 替换配置文件中的域名
sed "s/your-domain.com/$DOMAIN/g" $PROJECT_DIR/nginx.conf > /tmp/nginx-$PROJECT_NAME.conf

# 创建静态文件目录的软链接
if [ ! -L "/var/www/beauty-notification/web" ]; then
    ln -sf $PROJECT_DIR/web /var/www/beauty-notification/web
fi

# 复制 Nginx 配置
cp /tmp/nginx-$PROJECT_NAME.conf /etc/nginx/sites-available/$NGINX_SITE_NAME

# 创建软链接
if [ ! -L "/etc/nginx/sites-enabled/$NGINX_SITE_NAME" ]; then
    ln -s /etc/nginx/sites-available/$NGINX_SITE_NAME /etc/nginx/sites-enabled/
fi

# 测试 Nginx 配置
echo ""
echo -e "${YELLOW}测试 Nginx 配置...${NC}"
nginx -t

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Nginx 配置正确${NC}"
    systemctl reload nginx
else
    echo -e "${RED}❌ Nginx 配置错误,请检查${NC}"
    exit 1
fi

echo ""
echo "==> 步骤 7: 配置数据库"
echo ""

echo -e "${YELLOW}请确保已创建数据库:${NC}"
echo "CREATE DATABASE beauty_notification CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
echo ""
read -p "数据库已创建? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}请先创建数据库再继续${NC}"
    exit 1
fi

echo ""
echo "==> 步骤 8: 启动应用"
echo ""

# 使用 PM2 启动
cd $PROJECT_DIR
pm2 start ecosystem.config.js

# 设置 PM2 开机自启
pm2 startup systemd -u $SUDO_USER --hp $HOME
pm2 save

echo -e "${GREEN}✅ 应用启动成功${NC}"

echo ""
echo "==> 步骤 9: 配置 SSL 证书 (可选)"
echo ""

read -p "是否配置 SSL 证书? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # 安装 certbot
    if ! command -v certbot &> /dev/null; then
        echo -e "${YELLOW}安装 Certbot...${NC}"
        apt-get install -y certbot python3-certbot-nginx
    fi

    # 获取证书
    certbot --nginx -d $DOMAIN

    echo -e "${GREEN}✅ SSL 证书配置完成${NC}"
else
    echo -e "${YELLOW}跳过 SSL 配置${NC}"
fi

echo ""
echo "========================================="
echo "✅ 部署完成!"
echo "========================================="
echo ""
echo "📋 部署信息:"
echo "  - 项目目录: $PROJECT_DIR"
echo "  - Node.js 版本: $(node -v)"
echo "  - PM2 进程名: $PROJECT_NAME"
echo "  - 域名: $DOMAIN"
echo ""
echo "🔗 访问地址:"
echo "  - 管理后台: https://$DOMAIN/admin/dashboard/"
echo "  - API 健康检查: https://$DOMAIN/api/health"
echo "  - Webhook 地址: https://$DOMAIN/api/douyin/webhook"
echo ""
echo "📝 常用命令:"
echo "  - 查看日志: pm2 logs $PROJECT_NAME"
echo "  - 重启应用: pm2 restart $PROJECT_NAME"
echo "  - 停止应用: pm2 stop $PROJECT_NAME"
echo "  - 查看状态: pm2 status"
echo "  - Nginx 日志: tail -f /var/log/nginx/beauty-notification-*.log"
echo ""
echo "⚙️  下一步:"
echo "  1. 编辑 .env 配置: nano $PROJECT_DIR/.env"
echo "  2. 在抖音平台配置 Webhook: https://$DOMAIN/api/douyin/webhook"
echo "  3. 配置授权回调地址: https://$DOMAIN/api/douyin/callback"
echo "  4. 访问管理后台授权店铺"
echo ""
echo "========================================="

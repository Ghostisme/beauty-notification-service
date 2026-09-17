#!/bin/bash

# 美容店来客通知系统 - Git 部署脚本
# 使用方式: curl -fsSL https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-git.sh | bash

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
REPO_URL="https://github.com/Ghostisme/beauty-notification-service.git"
PROJECT_DIR="/var/www/beauty-notification"
PROJECT_NAME="beauty-notification"

# Git 加速配置 - 使用镜像站加速克隆
USE_MIRROR="${USE_MIRROR:-true}"
GIT_MIRROR="https://ghproxy.com/"

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}美容店来客通知系统 - Git 部署${NC}"
echo -e "${BLUE}=========================================${NC}"

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}请使用 sudo 运行此脚本${NC}"
    exit 1
fi

# 获取原始用户
ORIGINAL_USER=${SUDO_USER:-$USER}
ORIGINAL_HOME=$(eval echo ~$ORIGINAL_USER)

echo ""
echo -e "${GREEN}==> 步骤 1: 检查系统环境${NC}"
echo ""

# 检查 Git
if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}安装 Git...${NC}"
    apt-get update
    apt-get install -y git
fi
echo -e "${GREEN}✅ Git 已安装: $(git --version)${NC}"

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ 未检测到 Node.js,请先安装 Node.js${NC}"
    exit 1
fi

NODE_CURRENT_VERSION=$(node -v)
echo -e "${GREEN}✅ Node.js 已安装: ${NODE_CURRENT_VERSION}${NC}"

# 检查 npm
if ! command -v npm &> /dev/null; then
    echo -e "${RED}❌ 未检测到 npm,请先安装 npm${NC}"
    exit 1
fi
echo -e "${GREEN}✅ npm 已安装: $(npm -v)${NC}"

# 安装 PM2
if ! command -v pm2 &> /dev/null; then
    echo -e "${YELLOW}安装 PM2...${NC}"
    npm install -g pm2
fi
echo -e "${GREEN}✅ PM2 已安装: $(pm2 -v)${NC}"

echo ""
echo -e "${GREEN}==> 步骤 2: 克隆/更新代码${NC}"
echo ""

if [ -d "$PROJECT_DIR/.git" ]; then
    echo -e "${YELLOW}项目已存在,拉取最新代码...${NC}"
    cd $PROJECT_DIR

    # 保存本地修改(如果有)
    git stash

    # 拉取最新代码
    git pull origin main

    # 恢复本地修改
    git stash pop || true

    echo -e "${GREEN}✅ 代码更新完成${NC}"
else
    echo -e "${YELLOW}克隆代码仓库...${NC}"
    mkdir -p $(dirname $PROJECT_DIR)

    # 使用镜像加速克隆
    CLONE_URL=$REPO_URL
    if [ "$USE_MIRROR" = "true" ]; then
        CLONE_URL="${GIT_MIRROR}${REPO_URL}"
        echo -e "${BLUE}使用镜像加速: ${CLONE_URL}${NC}"
    fi

    # 尝试克隆,如果失败则回退到原始地址
    if ! git clone --depth 1 $CLONE_URL $PROJECT_DIR; then
        echo -e "${YELLOW}镜像克隆失败,尝试直接克隆...${NC}"
        git clone --depth 1 $REPO_URL $PROJECT_DIR
    fi

    cd $PROJECT_DIR
    echo -e "${GREEN}✅ 代码克隆完成${NC}"
fi

# 设置目录权限
chown -R $ORIGINAL_USER:$ORIGINAL_USER $PROJECT_DIR

echo ""
echo -e "${GREEN}==> 步骤 3: 配置环境变量${NC}"
echo ""

# 检查 .env 文件
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo -e "${YELLOW}⚠️  已创建 .env 文件,请编辑配置${NC}"
    echo -e "${BLUE}编辑命令: sudo nano $PROJECT_DIR/.env${NC}"
    echo ""
    read -p "是否现在编辑配置? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        nano $PROJECT_DIR/.env
    else
        echo -e "${YELLOW}请稍后手动编辑: $PROJECT_DIR/.env${NC}"
    fi
else
    echo -e "${GREEN}✅ .env 文件已存在${NC}"
fi

echo ""
echo -e "${GREEN}==> 步骤 4: 安装依赖${NC}"
echo ""

cd $PROJECT_DIR
npm install --production

echo -e "${GREEN}✅ 依赖安装完成${NC}"

echo ""
echo -e "${GREEN}==> 步骤 5: 配置 PM2${NC}"
echo ""

# 停止旧进程
pm2 delete $PROJECT_NAME 2>/dev/null || true

# 启动新进程
cd $PROJECT_DIR
pm2 start ecosystem.config.js

# 设置开机自启
pm2 startup systemd -u $ORIGINAL_USER --hp $ORIGINAL_HOME | grep -v "^PM2" | bash || true
pm2 save

echo -e "${GREEN}✅ PM2 配置完成${NC}"

echo ""
echo -e "${GREEN}==> 步骤 6: 配置 Nginx (可选)${NC}"
echo ""

read -p "是否配置 Nginx? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # 安装 Nginx
    if ! command -v nginx &> /dev/null; then
        echo -e "${YELLOW}安装 Nginx...${NC}"
        apt-get update
        apt-get install -y nginx
    fi

    # 询问域名
    read -p "请输入域名 (例: example.com): " DOMAIN

    # 复制配置文件
    if [ -f "$PROJECT_DIR/nginx.conf" ]; then
        sed "s/your-domain.com/$DOMAIN/g" "$PROJECT_DIR/nginx.conf" > "/etc/nginx/sites-available/$PROJECT_NAME"
        ln -sf "/etc/nginx/sites-available/$PROJECT_NAME" "/etc/nginx/sites-enabled/"

        # 测试配置
        nginx -t && systemctl reload nginx

        echo -e "${GREEN}✅ Nginx 配置完成${NC}"

        # 询问是否配置 SSL
        read -p "是否配置 SSL 证书? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if ! command -v certbot &> /dev/null; then
                apt-get install -y certbot python3-certbot-nginx
            fi
            certbot --nginx -d $DOMAIN
            echo -e "${GREEN}✅ SSL 证书配置完成${NC}"
        fi
    else
        echo -e "${YELLOW}未找到 nginx.conf 文件,跳过 Nginx 配置${NC}"
    fi
else
    echo -e "${YELLOW}跳过 Nginx 配置${NC}"
fi

echo ""
echo -e "${BLUE}=========================================${NC}"
echo -e "${GREEN}✅ 部署完成!${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""
echo -e "${BLUE}📋 部署信息:${NC}"
echo -e "  - 项目目录: ${GREEN}$PROJECT_DIR${NC}"
echo -e "  - Git 仓库: ${GREEN}$REPO_URL${NC}"
echo -e "  - PM2 进程: ${GREEN}$PROJECT_NAME${NC}"
echo ""
echo -e "${BLUE}🔗 访问地址:${NC}"
echo -e "  - 本地: ${GREEN}http://localhost:3000${NC}"
if [ ! -z "$DOMAIN" ]; then
    echo -e "  - 域名: ${GREEN}https://$DOMAIN${NC}"
    echo -e "  - 管理后台: ${GREEN}https://$DOMAIN/admin/dashboard/${NC}"
fi
echo ""
echo -e "${BLUE}📝 常用命令:${NC}"
echo -e "  - 查看日志: ${GREEN}pm2 logs $PROJECT_NAME${NC}"
echo -e "  - 重启应用: ${GREEN}pm2 restart $PROJECT_NAME${NC}"
echo -e "  - 查看状态: ${GREEN}pm2 status${NC}"
echo -e "  - 更新代码: ${GREEN}cd $PROJECT_DIR && git pull && npm install && pm2 reload $PROJECT_NAME${NC}"
echo ""
echo -e "${BLUE}⚙️  下一步:${NC}"
echo -e "  1. 编辑配置: ${GREEN}sudo nano $PROJECT_DIR/.env${NC}"
echo -e "  2. 重启应用: ${GREEN}pm2 restart $PROJECT_NAME${NC}"
echo -e "  3. 在抖音平台配置 Webhook"
echo -e "  4. 访问管理后台授权店铺"
echo ""
echo -e "${BLUE}=========================================${NC}"

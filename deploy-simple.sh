#!/bin/bash

# 简化部署脚本 - 避免 curl 管道问题
# 使用方法:
#   wget https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-simple.sh
#   chmod +x deploy-simple.sh
#   sudo ./deploy-simple.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}=========================================${NC}"
echo -e "${YELLOW}美容店来客通知系统 - 简化部署${NC}"
echo -e "${YELLOW}=========================================${NC}"
echo ""

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}请使用 sudo 执行此脚本${NC}"
  exit 1
fi

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ 未检测到 Node.js${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Node.js: $(node -v)${NC}"

# 检查 npm
if ! command -v npm &> /dev/null; then
    echo -e "${RED}❌ 未检测到 npm${NC}"
    exit 1
fi

echo -e "${GREEN}✅ npm: $(npm -v)${NC}"

# 检查 PM2
if ! command -v pm2 &> /dev/null; then
    echo -e "${YELLOW}⚠️  未检测到 PM2,正在安装...${NC}"
    npm install -g pm2
fi

echo -e "${GREEN}✅ PM2: $(pm2 -v)${NC}"
echo ""

# 设置部署目录
DEPLOY_DIR="/var/www/beauty-notification"
REPO_URL="https://github.com/Ghostisme/beauty-notification-service.git"

echo -e "${YELLOW}==> 步骤 1: 准备部署目录${NC}"

if [ -d "$DEPLOY_DIR" ]; then
    echo -e "${YELLOW}⚠️  目录已存在,将进行更新${NC}"
    cd "$DEPLOY_DIR"
    git pull origin main
else
    echo -e "${YELLOW}克隆代码仓库...${NC}"
    mkdir -p /var/www
    cd /var/www
    git clone "$REPO_URL" beauty-notification
    cd "$DEPLOY_DIR"
fi

echo -e "${GREEN}✅ 代码准备完成${NC}"
echo ""

# 配置环境变量
echo -e "${YELLOW}==> 步骤 2: 配置环境变量${NC}"

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${YELLOW}⚠️  已创建 .env 文件,请编辑配置:${NC}"
        echo -e "  nano .env"
        echo ""
        echo -e "${YELLOW}配置完成后,执行以下命令启动服务:${NC}"
        echo -e "  cd $DEPLOY_DIR"
        echo -e "  npm install --production"
        echo -e "  pm2 start ecosystem.config.js"
        echo -e "  pm2 save"
        echo -e "  pm2 startup"
        echo ""
        exit 0
    else
        echo -e "${RED}❌ 未找到 .env.example 文件${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✅ .env 文件已存在${NC}"
fi

echo ""

# 安装依赖
echo -e "${YELLOW}==> 步骤 3: 安装依赖${NC}"
npm install --production
echo -e "${GREEN}✅ 依赖安装完成${NC}"
echo ""

# 启动服务
echo -e "${YELLOW}==> 步骤 4: 启动服务${NC}"

# 检查是否已经在运行
if pm2 describe beauty-notification &> /dev/null; then
    echo -e "${YELLOW}服务已在运行,重启中...${NC}"
    pm2 restart beauty-notification
else
    echo -e "${YELLOW}首次启动服务...${NC}"
    pm2 start ecosystem.config.js
fi

echo -e "${GREEN}✅ 服务启动完成${NC}"
echo ""

# 设置开机自启
echo -e "${YELLOW}==> 步骤 5: 设置开机自启${NC}"
pm2 save
pm2 startup | tail -n 1 | bash
echo -e "${GREEN}✅ 开机自启设置完成${NC}"
echo ""

# 显示状态
echo -e "${YELLOW}==> 服务状态${NC}"
pm2 list
echo ""

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}✅ 部署完成!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo -e "查看日志: ${YELLOW}pm2 logs beauty-notification${NC}"
echo -e "查看状态: ${YELLOW}pm2 status${NC}"
echo -e "重启服务: ${YELLOW}pm2 restart beauty-notification${NC}"
echo ""
echo -e "管理后台: ${YELLOW}http://your-domain/admin/dashboard/${NC}"
echo -e "健康检查: ${YELLOW}http://your-domain/api/health${NC}"
echo ""

#!/bin/bash

# 快速修复脚本 - 创建 Node.js 符号链接
# 解决 sudo 环境下找不到 Node.js 的问题

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}=========================================${NC}"
echo -e "${YELLOW}Node.js 环境修复工具${NC}"
echo -e "${YELLOW}=========================================${NC}"
echo ""

# 检查当前用户环境的 Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ 当前用户环境未安装 Node.js${NC}"
    exit 1
fi

NODE_PATH=$(which node)
NPM_PATH=$(which npm)

echo -e "${GREEN}✅ 检测到 Node.js:${NC}"
echo -e "  - Node: ${NODE_PATH}"
echo -e "  - npm: ${NPM_PATH}"
echo -e "  - 版本: $(node -v)"
echo ""

# 检查 sudo 环境
echo -e "${YELLOW}检查 sudo 环境...${NC}"
if sudo which node &> /dev/null; then
    echo -e "${GREEN}✅ sudo 环境已能访问 Node.js,无需修复${NC}"
    sudo node -v
    exit 0
fi

echo -e "${YELLOW}⚠️  sudo 环境无法访问 Node.js,开始创建符号链接...${NC}"
echo ""

# 创建符号链接
echo -e "${YELLOW}创建符号链接到 /usr/local/bin/ ...${NC}"

sudo ln -sf "$NODE_PATH" /usr/local/bin/node
echo -e "${GREEN}✅ node -> $NODE_PATH${NC}"

sudo ln -sf "$NPM_PATH" /usr/local/bin/npm
echo -e "${GREEN}✅ npm -> $NPM_PATH${NC}"

# 如果存在 npx,也创建链接
if command -v npx &> /dev/null; then
    NPX_PATH=$(which npx)
    sudo ln -sf "$NPX_PATH" /usr/local/bin/npx
    echo -e "${GREEN}✅ npx -> $NPX_PATH${NC}"
fi

# 如果存在 PM2,也创建链接
if command -v pm2 &> /dev/null; then
    PM2_PATH=$(which pm2)
    sudo ln -sf "$PM2_PATH" /usr/local/bin/pm2
    echo -e "${GREEN}✅ pm2 -> $PM2_PATH${NC}"
else
    echo -e "${YELLOW}⚠️  未检测到 PM2,将在部署时自动安装${NC}"
fi

echo ""

# 验证
echo -e "${YELLOW}验证修复结果...${NC}"
if sudo node -v &> /dev/null; then
    echo -e "${GREEN}✅ 修复成功!${NC}"
    echo -e "  - sudo node -v: $(sudo node -v)"
    echo -e "  - sudo npm -v: $(sudo npm -v)"

    if sudo pm2 -v &> /dev/null 2>&1; then
        echo -e "  - sudo pm2 -v: $(sudo pm2 -v)"
    fi

    echo ""
    echo -e "${GREEN}现在可以执行部署脚本了:${NC}"
    echo -e "  curl -fsSL https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-git.sh | sudo bash"
else
    echo -e "${RED}❌ 修复失败,请手动检查${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}=========================================${NC}"
echo -e "${GREEN}✅ 修复完成${NC}"
echo -e "${YELLOW}=========================================${NC}"

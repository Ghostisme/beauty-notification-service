#!/bin/bash

# 智能更新脚本
# 在服务器上运行此脚本快速更新代码
# 自动检测代码变更和依赖变化

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PROJECT_DIR="/var/www/beauty-notification"
PROJECT_NAME="beauty-notification"

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}🔄 开始智能更新...${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# 进入项目目录
cd $PROJECT_DIR

# 1. 备份当前 .env
echo -e "${YELLOW}📋 备份配置文件...${NC}"
cp .env .env.backup
echo -e "${GREEN}✅ 配置已备份${NC}"
echo ""

# 2. 记录更新前的状态
echo -e "${YELLOW}📊 检查当前状态...${NC}"
BEFORE_COMMIT=$(git rev-parse HEAD)
BEFORE_PACKAGE_HASH=$(md5sum package.json 2>/dev/null | awk '{print $1}' || echo "none")

echo -e "  - 当前版本: ${GREEN}${BEFORE_COMMIT:0:7}${NC}"
echo -e "  - package.json: ${GREEN}${BEFORE_PACKAGE_HASH:0:7}${NC}"
echo ""

# 3. 拉取最新代码
echo -e "${YELLOW}📥 拉取最新代码...${NC}"
git fetch origin main

# 检查是否有更新
if git diff --quiet HEAD origin/main; then
    echo -e "${GREEN}✅ 代码已是最新,无需更新${NC}"
    rm .env.backup
    exit 0
fi

# 显示即将应用的变更
echo -e "${BLUE}📝 变更摘要:${NC}"
git log --oneline HEAD..origin/main | head -5
echo ""

# 拉取代码
git pull origin main
echo -e "${GREEN}✅ 代码更新完成${NC}"
echo ""

# 4. 检测变更
echo -e "${YELLOW}🔍 分析变更内容...${NC}"
AFTER_COMMIT=$(git rev-parse HEAD)
AFTER_PACKAGE_HASH=$(md5sum package.json 2>/dev/null | awk '{print $1}' || echo "none")

# 检查代码是否有变化
if [ "$BEFORE_COMMIT" != "$AFTER_COMMIT" ]; then
    echo -e "${BLUE}📂 代码文件变更:${NC}"
    git diff --name-status $BEFORE_COMMIT $AFTER_COMMIT | head -10
    CODE_CHANGED=true
else
    CODE_CHANGED=false
fi
echo ""

# 检查依赖是否有变化
if [ "$BEFORE_PACKAGE_HASH" != "$AFTER_PACKAGE_HASH" ]; then
    echo -e "${YELLOW}📦 检测到依赖变化,需要重新安装...${NC}"
    DEPS_CHANGED=true
else
    echo -e "${GREEN}✅ 依赖无变化,跳过安装${NC}"
    DEPS_CHANGED=false
fi
echo ""

# 5. 恢复 .env
if [ -f .env.backup ]; then
    cp .env.backup .env
    rm .env.backup
    echo -e "${GREEN}✅ 配置文件已恢复${NC}"
fi
echo ""

# 6. 安装依赖(如果需要)
if [ "$DEPS_CHANGED" = true ]; then
    echo -e "${YELLOW}📦 安装依赖(可能需要几分钟)...${NC}"
    npm install --production
    echo -e "${GREEN}✅ 依赖安装完成${NC}"
else
    echo -e "${BLUE}⏭️  跳过依赖安装${NC}"
fi
echo ""

# 7. 重启应用
echo -e "${YELLOW}♻️  重启应用...${NC}"
if [ "$DEPS_CHANGED" = true ]; then
    # 依赖变化时完全重启
    pm2 restart $PROJECT_NAME
    echo -e "${GREEN}✅ 应用已重启(完全重启)${NC}"
else
    # 仅代码变化时热重载
    pm2 reload $PROJECT_NAME
    echo -e "${GREEN}✅ 应用已重载(零停机)${NC}"
fi
echo ""

# 8. 显示更新摘要
echo -e "${BLUE}=========================================${NC}"
echo -e "${GREEN}✅ 更新完成!${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""
echo -e "${BLUE}📊 更新摘要:${NC}"
echo -e "  - 版本: ${YELLOW}${BEFORE_COMMIT:0:7}${NC} → ${GREEN}${AFTER_COMMIT:0:7}${NC}"
if [ "$CODE_CHANGED" = true ]; then
    echo -e "  - 代码: ${GREEN}已更新${NC}"
else
    echo -e "  - 代码: ${BLUE}无变化${NC}"
fi
if [ "$DEPS_CHANGED" = true ]; then
    echo -e "  - 依赖: ${GREEN}已更新${NC}"
else
    echo -e "  - 依赖: ${BLUE}无变化${NC}"
fi
echo ""
echo -e "${BLUE}📝 后续操作:${NC}"
echo -e "  - 查看日志: ${GREEN}pm2 logs $PROJECT_NAME${NC}"
echo -e "  - 查看状态: ${GREEN}pm2 status${NC}"
echo -e "  - 访问后台: ${GREEN}https://notification.hongquanquan.cn/admin/dashboard/${NC}"
echo ""
echo -e "${BLUE}=========================================${NC}"

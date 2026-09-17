#!/bin/bash

# 监控更新脚本
# 自动检查 GitHub 更新并执行更新操作

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_DIR="/var/www/beauty-notification"
REPO_URL="https://github.com/Ghostisme/beauty-notification-service.git"

cd $PROJECT_DIR

echo -e "${BLUE}🔍 检查远程更新...${NC}"

# 获取远程最新提交
git fetch origin main --quiet

LOCAL_COMMIT=$(git rev-parse HEAD)
REMOTE_COMMIT=$(git rev-parse origin/main)

if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
    echo -e "${GREEN}✅ 已是最新版本${NC}"
    exit 0
fi

echo -e "${YELLOW}📢 发现新版本!${NC}"
echo -e "${BLUE}变更日志:${NC}"
git log --oneline $LOCAL_COMMIT..$REMOTE_COMMIT | head -5
echo ""

# 询问是否更新
read -p "是否立即更新? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    bash update.sh
else
    echo -e "${YELLOW}⏸️  已取消更新${NC}"
fi

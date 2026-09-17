#!/bin/bash

# 快速更新脚本
# 在服务器上运行此脚本快速更新代码

set -e

PROJECT_DIR="/var/www/beauty-notification"
PROJECT_NAME="beauty-notification"

echo "🔄 开始更新..."

# 进入项目目录
cd $PROJECT_DIR

# 备份当前 .env
cp .env .env.backup

# 拉取最新代码
echo "📥 拉取最新代码..."
git pull origin main

# 恢复 .env (如果被覆盖)
if [ -f .env.backup ]; then
    cp .env.backup .env
    rm .env.backup
fi

# 安装依赖
echo "📦 安装依赖..."
npm install --production

# 重启应用
echo "♻️  重启应用..."
pm2 reload $PROJECT_NAME

echo "✅ 更新完成!"
echo ""
echo "查看日志: pm2 logs $PROJECT_NAME"

#!/bin/bash

# 美容店来客通知系统 - 简化部署脚本
# 用于快速部署到服务器

set -e

echo "========================================="
echo "美容店来客通知系统 - 部署开始"
echo "========================================="

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "❌ 未安装 Node.js，请先安装 Node.js 16+"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 16 ]; then
    echo "❌ Node.js 版本过低，需要 16+，当前版本: $(node -v)"
    exit 1
fi

echo "✅ Node.js 版本: $(node -v)"

# 安装依赖
echo ""
echo "📦 安装依赖..."
npm install --production

# 检查 .env 文件
if [ ! -f .env ]; then
    echo ""
    echo "⚠️  未找到 .env 文件"
    echo "正在创建 .env 文件..."
    cp .env.example .env
    echo "✅ 已创建 .env 文件，请编辑配置后重新运行"
    echo ""
    echo "需要配置的项目:"
    echo "  1. DOUYIN_CLIENT_KEY - 抖音开放平台应用 Key"
    echo "  2. DOUYIN_CLIENT_SECRET - 抖音开放平台应用 Secret"
    echo "  3. DOUYIN_SPI_TOKEN - 自定义 SPI 回调验证 Token"
    echo "  4. WEWORK_CORP_ID - 企业微信企业 ID"
    echo "  5. WEWORK_AGENT_ID - 企业微信应用 ID"
    echo "  6. WEWORK_SECRET - 企业微信应用 Secret"
    echo "  7. WEWORK_SENDER_USERID - 企业微信发送者 UserID"
    echo "  8. DB_* - 数据库配置"
    echo ""
    exit 1
fi

echo "✅ 找到 .env 配置文件"

# 检查 MySQL
echo ""
echo "🗄️  检查数据库连接..."
if command -v mysql &> /dev/null; then
    echo "✅ MySQL 客户端已安装"
else
    echo "⚠️  未找到 MySQL 客户端"
fi

# 创建必要的目录
echo ""
echo "📁 创建必要目录..."
mkdir -p data
mkdir -p logs
echo "✅ 目录创建完成"

# 提示部署信息
echo ""
echo "========================================="
echo "✅ 部署准备完成!"
echo "========================================="
echo ""
echo "📋 下一步操作:"
echo ""
echo "1. 确保数据库已创建并可连接"
echo "   CREATE DATABASE beauty_notification CHARACTER SET utf8mb4;"
echo ""
echo "2. 启动服务:"
echo "   npm start"
echo ""
echo "3. 访问管理后台:"
echo "   http://your-domain:3000/admin/dashboard/"
echo ""
echo "4. 配置抖音 Webhook:"
echo "   URL: https://your-domain/api/douyin/webhook"
echo "   Token: 你在 .env 中设置的 DOUYIN_SPI_TOKEN"
echo ""
echo "5. 配置授权回调:"
echo "   URL: https://your-domain/api/douyin/callback"
echo ""
echo "========================================="

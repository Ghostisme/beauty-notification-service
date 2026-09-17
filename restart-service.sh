#!/bin/bash

# 美容通知服务重启脚本
# 服务器: 47.103.32.12
# 域名: https://notification.hongquanquan.cn

echo "🔄 正在重启服务..."

cd /var/www/beauty-notification

# 重启 PM2 服务
pm2 restart beauty-notification

# 等待服务启动
sleep 3

# 检查服务状态
echo ""
echo "📊 服务状态:"
pm2 status beauty-notification

# 查看最新日志
echo ""
echo "📋 最新日志 (最后20行):"
pm2 logs beauty-notification --lines 20 --nostream

# 测试健康检查
echo ""
echo "🏥 健康检查:"
curl -s http://localhost:3000/api/health | jq . || echo "健康检查失败"

echo ""
echo "✅ 重启完成!"
echo "📍 SPI 地址: https://notification.hongquanquan.cn/api/douyin/spi/callback?token=6256fce5e13728ef8659d8a6d30e7c0cc53231261f07787808d615aeff124bca"

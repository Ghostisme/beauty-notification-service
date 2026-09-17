#!/bin/bash

# 测试脚本 - 验证服务是否正常工作

BASE_URL="http://localhost:3000"

echo "=================================="
echo "美容通知系统 - 功能测试"
echo "=================================="
echo ""

# 1. 健康检查
echo "1️⃣  健康检查..."
response=$(curl -s -w "\n%{http_code}" ${BASE_URL}/health)
status_code=$(echo "$response" | tail -n 1)
body=$(echo "$response" | head -n -1)

if [ "$status_code" = "200" ]; then
    echo "✅ 服务运行正常"
    echo "$body" | python3 -m json.tool
else
    echo "❌ 服务异常 (HTTP $status_code)"
    exit 1
fi

echo ""

# 2. 查看门店列表
echo "2️⃣  查看门店列表..."
stores=$(curl -s ${BASE_URL}/api/stores)
store_count=$(echo "$stores" | python3 -c "import sys, json; print(json.load(sys.stdin)['total'])")
echo "✅ 已配置 $store_count 个门店"

# 获取第一个门店ID用于测试
first_store_id=$(echo "$stores" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data['stores'][0]['id'] if data['stores'] else 'store_001')")
echo "测试门店: $first_store_id"

echo ""

# 3. 测试手动推送
echo "3️⃣  测试手动推送..."
push_response=$(curl -s -X POST ${BASE_URL}/api/notify \
  -H "Content-Type: application/json" \
  -d "{
    \"storeId\": \"$first_store_id\",
    \"orderInfo\": {
      \"orderId\": \"TEST_$(date +%s)\",
      \"customerName\": \"张女士\",
      \"phone\": \"138****8888\",
      \"service\": \"美甲服务\",
      \"amount\": \"99\",
      \"appointmentTime\": \"$(date '+%Y-%m-%d %H:%M')\"
    }
  }")

if echo "$push_response" | grep -q "success"; then
    echo "✅ 推送成功"
    echo "$push_response" | python3 -m json.tool
else
    echo "❌ 推送失败"
    echo "$push_response"
fi

echo ""

# 4. 查看队列状态
echo "4️⃣  查看队列状态..."
queue_stats=$(curl -s ${BASE_URL}/api/queue/stats)
echo "$queue_stats" | python3 -m json.tool

echo ""

# 5. 测试广播推送
echo "5️⃣  测试广播推送（所有门店）..."
broadcast_response=$(curl -s -X POST ${BASE_URL}/api/notify/broadcast \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"📢 系统测试消息\\n\\n这是一条测试广播消息，请忽略。\\n\\n时间: $(date '+%Y-%m-%d %H:%M:%S')\"
  }")

if echo "$broadcast_response" | grep -q "success"; then
    echo "✅ 广播成功"
    echo "$broadcast_response" | python3 -m json.tool
else
    echo "❌ 广播失败"
    echo "$broadcast_response"
fi

echo ""
echo "=================================="
echo "测试完成！请检查企微群是否收到消息"
echo "=================================="
echo ""
echo "💡 提示："
echo "- 如果收到消息，说明系统正常工作"
echo "- 如果没收到，检查 Webhook 地址是否正确"
echo "- 查看日志: docker-compose logs -f"
echo ""

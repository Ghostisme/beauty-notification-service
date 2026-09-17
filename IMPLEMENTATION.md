# 实施指南

## 完整实施时间线

### 第1周：准备阶段

#### Day 1-2: 企业微信配置
- [ ] 注册并认证企业微信（300元，等待1-3天审核）
- [ ] 创建第一个测试群
- [ ] 添加群机器人，测试 Webhook

#### Day 3-4: 抖音开放平台
- [ ] 注册抖音开放平台账号
- [ ] 创建应用，记录 App ID 和 Secret
- [ ] 申请订单推送权限（等待3-5天审核）

#### Day 5-7: 服务器准备
- [ ] 购买云服务器（推荐阿里云 1核2G）
- [ ] 配置域名和 SSL 证书（可选）
- [ ] 运行部署脚本

### 第2周：批量配置

#### Day 8-10: 创建500个群
- [ ] 按门店创建企微客户群
- [ ] 为每个群添加机器人
- [ ] 使用收集工具整理 Webhook

#### Day 11-12: 配置文件
- [ ] 编辑 `data/groups.json`
- [ ] 填入500个门店配置
- [ ] 验证配置格式

#### Day 13-14: 测试验证
- [ ] 运行测试脚本
- [ ] 验证推送到各门店群
- [ ] 调整消息格式

### 第3周：对接抖音

#### Day 15-16: 配置回调
- [ ] 等待抖音权限审核通过
- [ ] 配置订单推送回调地址
- [ ] 完成回调验证

#### Day 17-18: 真实订单测试
- [ ] 在抖音下测试订单
- [ ] 验证推送到对应门店群
- [ ] 调优消息格式

#### Day 19-21: 全量上线
- [ ] 所有门店开始接收通知
- [ ] 监控系统运行状态
- [ ] 收集反馈并优化

---

## 详细操作手册

### 1. 企业微信群批量创建方案

**方案A：Excel + 批量操作**

```bash
1. 准备门店清单 Excel：
   列A: 门店ID
   列B: 门店名称
   列C: 地区
   列D: Webhook（待填）

2. 逐个创建群并填入 Webhook
3. 导出为 CSV，转换为 JSON
```

**方案B：使用企微管理后台**

```bash
如果门店数量大，可以联系企微官方
看是否有批量创建群的接口或工具
```

### 2. 门店ID与抖音POI映射

**抖音门店与系统门店ID的对应关系：**

```javascript
// 在 src/douyin.js 的 _extractStoreId 函数中配置
// 方案1: 直接使用抖音 POI ID
return `store_${data.poi_id}`;

// 方案2: 建立映射表
const poiMapping = {
  '123456789': 'store_001',  // 抖音POI ID → 系统门店ID
  '987654321': 'store_002'
};
return poiMapping[data.poi_id] || 'unknown';
```

### 3. 消息格式自定义

编辑 [src/server.js](src/server.js) 的 `formatOrderMessage` 函数：

```javascript
function formatOrderMessage(storeName, orderData) {
  // 自定义你的消息格式
  return `
🔔 ${storeName} - 新客户通知

📝 订单：${orderData.orderId}
👤 客户：${orderData.customerName}
📱 电话：${orderData.phone}
💅 项目：${orderData.service}
💰 金额：¥${orderData.amount}
⏰ 时间：${orderData.appointmentTime}

请及时联系客户！
  `.trim();
}
```

---

## 常见问题

### Q1: 企业微信认证需要什么资料？
**A:** 营业执照、法人身份证、对公账户（或个体户信息），300元认证费。

### Q2: 500个群机器人怎么快速创建？
**A:** 使用提供的 `webhook-collector.html` 工具，边创建边录入，最后一键导出 JSON。

### Q3: 抖音订单推送权限申请被拒怎么办？
**A:** 确保：
1. 有真实的美容门店营业执照
2. 抖音账号有认证的企业号
3. 使用场景描述详细

### Q4: 如何测试单个门店的推送？
**A:** 使用测试接口：

```bash
curl -X POST http://服务器IP:3000/api/notify \
  -H "Content-Type: application/json" \
  -d '{
    "storeId": "store_001",
    "orderInfo": {
      "orderId": "TEST123",
      "customerName": "测试客户",
      "phone": "138****8888",
      "service": "美甲",
      "amount": "99"
    }
  }'
```

### Q5: 如何查看推送失败的原因？
**A:** 查看日志：

```bash
docker-compose logs -f notification-service
```

### Q6: 系统能否支持多个抖音账号？
**A:** 可以，配置多个 Webhook 回调地址，或在代码中区分 App ID。

### Q7: 如何备份配置？
**A:** 定期备份 `data/groups.json`：

```bash
cp data/groups.json data/groups.json.backup.$(date +%Y%m%d)
```

---

## 成本明细

| 项目 | 费用 | 周期 |
|------|------|------|
| 企业微信认证 | 300元 | 年付 |
| 云服务器（1核2G2M） | 108-298元 | 年付 |
| 域名（可选） | 50-80元 | 年付 |
| **首年总计** | **458-678元** | - |
| **续费总计** | **598-678元/年** | - |

---

## 技术支持清单

部署完成后，你需要掌握的命令：

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 查看日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 查看状态
beauty-monitor

# 更新代码
git pull && docker-compose up -d --build

# 查看队列
curl http://localhost:3000/api/queue/stats

# 测试推送
bash test.sh
```

---

## 下一步

完成基础部署后，可以考虑的扩展功能：

1. **数据统计**：记录每个门店的订单数量
2. **客户管理**：将客户信息存入数据库
3. **多渠道推送**：同时推送到钉钉、飞书等
4. **消息模板**：支持不同类型的通知消息
5. **报表生成**：每日/每周订单统计报表

需要帮助实现这些功能吗？

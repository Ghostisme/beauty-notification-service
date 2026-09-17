/**
 * 数据存储使用说明
 * 
 * 本系统支持三种存储方式:
 * 1. MySQL - 生产环境推荐,功能完整
 * 2. JSON - 开发测试环境,轻量级文件存储
 * 3. TXT - 日志模式,适合简单记录
 */

## 配置存储类型

在 `.env` 文件中设置:

```env
# 存储类型: mysql | json | txt
STORAGE_TYPE=json

# 数据存储目录(json/txt 模式使用)
STORAGE_DATA_DIR=./data
```

## MySQL 模式

### 优势
- ✅ 完整的关系型数据库功能
- ✅ 高性能查询和索引
- ✅ 支持事务和并发
- ✅ 适合生产环境大量数据

### 配置

```env
STORAGE_TYPE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=beauty_user
DB_PASSWORD=your_password
DB_NAME=beauty_notification
```

### 数据表结构

**shops 表** - 店铺信息
- `shop_id` - 店铺唯一ID
- `shop_name` - 店铺名称
- `access_token` - 访问令牌
- `refresh_token` - 刷新令牌
- `token_expires_at` - 令牌过期时间
- `wework_chat_id` - 企微群ID
- `wework_chat_name` - 企微群名称

**messages 表** - 消息记录
- `shop_id` - 店铺ID
- `message_type` - 消息类型
- `customer_id` - 客户ID
- `customer_nickname` - 客户昵称
- `customer_phone` - 客户手机(脱敏)
- `message_content` - 消息内容
- `order_id` - 订单ID
- `order_amount` - 订单金额
- `pushed_to_wework` - 是否已推送
- `push_success` - 推送是否成功
- `error_message` - 错误信息
- `raw_data` - 原始JSON数据

## JSON 模式

### 优势
- ✅ 无需安装数据库
- ✅ 轻量级,适合开发测试
- ✅ 数据可视化,易于调试
- ✅ 快速部署

### 配置

```env
STORAGE_TYPE=json
STORAGE_DATA_DIR=./data
```

### 文件结构

```
data/
├── shops.json      # 店铺数据
└── messages.json   # 消息数据
```

### 数据格式示例

**shops.json**
```json
[
  {
    "shop_id": "shop_001",
    "shop_name": "美容店1号店",
    "access_token": "...",
    "refresh_token": "...",
    "token_expires_at": "2024-12-31T23:59:59.000Z",
    "wework_chat_id": "wrkxxx",
    "wework_chat_name": "美容店客户群",
    "created_at": "2024-01-01T00:00:00.000Z",
    "updated_at": "2024-01-15T10:30:00.000Z"
  }
]
```

**messages.json**
```json
[
  {
    "id": "msg_12345",
    "shop_id": "shop_001",
    "message_type": "order_new",
    "customer_id": "cust_001",
    "customer_nickname": "张女士",
    "customer_phone": "138****1234",
    "message_content": "预约了美容服务",
    "order_id": "order_001",
    "order_amount": 299.00,
    "pushed_to_wework": true,
    "push_success": true,
    "error_message": null,
    "raw_data": {...},
    "created_at": "2024-01-15T14:30:00.000Z"
  }
]
```

## TXT 模式

### 优势
- ✅ 最轻量,纯文本存储
- ✅ 易于日志分析和 grep 查询
- ✅ 适合简单监控和记录

### 配置

```env
STORAGE_TYPE=txt
STORAGE_DATA_DIR=./data/logs
```

### 文件结构

```
data/logs/
├── shops.txt       # 店铺操作日志
└── messages.txt    # 消息日志
```

### 数据格式 (Tab 分隔)

**messages.txt**
```
时间\t店铺ID\t消息类型\t客户ID\t客户昵称\t手机\t消息内容\t订单ID\t金额\t状态\t错误
2024-01-15T14:30:00.000Z	shop_001	order_new	cust_001	张女士	138****1234	预约了美容服务	order_001	299.00	SUCCESS	
```

## API 使用示例

### 初始化存储

```javascript
const storage = require('./src/storage');

// 在应用启动时初始化
await storage.initStorage();
```

### 保存消息

```javascript
await storage.saveMessage({
  shopId: 'shop_001',
  messageType: 'order_new',
  customerId: 'cust_001',
  customerNickname: '张女士',
  customerPhone: '138****1234',
  messageContent: '预约了美容服务',
  orderId: 'order_001',
  orderAmount: 299.00,
  pushedToWework: true,
  pushSuccess: true,
  errorMessage: null,
  rawData: {...}
});
```

### 查询消息

```javascript
// 获取所有消息
const allMessages = await storage.getMessages();

// 按店铺过滤
const shopMessages = await storage.getMessages({
  shopId: 'shop_001',
  limit: 50
});

// 按时间范围
const recentMessages = await storage.getMessages({
  startDate: '2024-01-01',
  endDate: '2024-01-31',
  limit: 100,
  offset: 0
});
```

### 店铺操作

```javascript
// 保存店铺
await storage.saveShop({
  shopId: 'shop_001',
  shopName: '美容店1号店',
  accessToken: '...',
  refreshToken: '...',
  tokenExpiresAt: new Date('2024-12-31')
});

// 获取所有店铺
const shops = await storage.getShops();

// 获取单个店铺
const shop = await storage.getShopById('shop_001');

// 更新店铺企微配置
await storage.updateShop('shop_001', {
  weworkChatId: 'wrkxxx',
  weworkChatName: '美容店客户群'
});
```

### 统计数据

```javascript
const stats = await storage.getStatistics();
// 返回:
// {
//   total_shops: 5,
//   today_messages: 23,
//   total_messages: 1250,
//   success_rate: 98,
//   total_customers: 856
// }
```

## 存储迁移

### 从 JSON 迁移到 MySQL

```javascript
const { JSONAdapter, MySQLAdapter } = require('./src/storage/adapter');

// 1. 读取 JSON 数据
const jsonStorage = new JSONAdapter({ dataDir: './data' });
await jsonStorage.init();

const shops = await jsonStorage.getShops();
const messages = await jsonStorage.getMessages();

// 2. 写入 MySQL
const mysqlStorage = new MySQLAdapter({
  host: 'localhost',
  user: 'root',
  password: 'password',
  database: 'beauty_notification'
});
await mysqlStorage.init();

// 3. 迁移数据
for (const shop of shops) {
  await mysqlStorage.saveShop(shop);
}

for (const message of messages) {
  await mysqlStorage.saveMessage(message);
}

console.log('迁移完成!');
```

## 性能对比

| 特性 | MySQL | JSON | TXT |
|------|-------|------|-----|
| 写入速度 | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 查询速度 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ |
| 数据完整性 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |
| 并发支持 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ |
| 部署复杂度 | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 适用场景 | 生产环境 | 开发测试 | 日志记录 |

## 最佳实践

### 生产环境
推荐使用 **MySQL** 存储:
- 数据安全可靠
- 查询性能优秀
- 支持高并发

### 开发测试
推荐使用 **JSON** 存储:
- 快速部署
- 方便调试
- 无需配置数据库

### 简单监控
可使用 **TXT** 存储:
- 极简部署
- 日志分析友好
- 适合轻量场景

## 数据备份

### JSON 模式备份
```bash
# 备份
cp -r data data_backup_$(date +%Y%m%d)

# 恢复
cp -r data_backup_20240115 data
```

### MySQL 模式备份
```bash
# 备份
mysqldump -u beauty_user -p beauty_notification > backup_$(date +%Y%m%d).sql

# 恢复
mysql -u beauty_user -p beauty_notification < backup_20240115.sql
```

## 故障排查

### MySQL 连接失败
```
检查项:
1. MySQL 服务是否运行
2. 配置的用户名密码是否正确
3. 数据库是否已创建
4. 网络连接是否正常
```

### JSON 文件读写错误
```
检查项:
1. data 目录权限是否正确
2. 磁盘空间是否充足
3. JSON 文件格式是否正确
```

### 数据丢失问题
```
解决方案:
1. 定期备份数据
2. 使用 MySQL 确保数据持久化
3. 检查日志文件排查问题
```

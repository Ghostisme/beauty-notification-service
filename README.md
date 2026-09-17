# 美容店来客通知系统

> 将抖音生活服务店铺的来客消息实时推送到企业微信客户群

## 📖 项目简介

本系统用于接收抖音生活服务平台的订单和客户消息,并自动推送到对应的企业微信外部客户群,帮助店铺及时响应客户需求。

### 核心功能

- ✅ **抖音 Webhook 接收**: 实时接收抖音平台推送的消息
- ✅ **店铺多账号管理**: 支持多个抖音店铺接入
- ✅ **企微群推送**: 自动推送到对应的企业微信客户群
- ✅ **管理后台**: 可视化管理界面
- ✅ **消息日志**: 完整的消息记录和推送状态
- ✅ **Token 自动刷新**: 自动维护授权状态

## 🎯 系统架构

```
┌─────────────┐        ┌─────────────┐        ┌─────────────┐
│   抖音店铺   │───────>│  本系统      │───────>│  企微客户群  │
│  (订单消息)  │ Webhook│  (转发处理)  │  推送  │  (通知店员)  │
└─────────────┘        └─────────────┘        └─────────────┘
```

## 🚀 快速开始

查看 [快速部署指南](./QUICK_START.md) 了解详细部署步骤。

### 最小化部署

```bash
# 1. 克隆代码
git clone <your-repo-url>
cd beauty-notification-service

# 2. 安装依赖
npm install

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入配置

# 4. 创建数据库
mysql -u root -p
CREATE DATABASE beauty_notification CHARACTER SET utf8mb4;

# 5. 启动服务
npm start
```

## 📱 管理后台

访问 `http://your-domain:3000/admin/dashboard/` 进入管理后台

### 主要功能

1. **系统概览**: 实时统计和最近消息
2. **店铺管理**: 授权和配置店铺
3. **消息日志**: 查看历史推送记录
4. **系统配置**: 环境变量和 Webhook 地址
5. **Webhook 测试**: 测试推送功能

## 🛠️ 技术栈

- **后端**: Node.js + Express
- **数据库**: MySQL
- **前端**: 原生 HTML + CSS + JavaScript
- **API 集成**: 抖音开放平台 + 企业微信 API

## 📂 项目结构

```
beauty-notification-service/
├── src/
│   ├── server.js              # 主服务器入口
│   ├── config/
│   │   └── index.js           # 配置管理
│   ├── database/
│   │   └── index.js           # 数据库操作
│   ├── services/
│   │   ├── douyin.js          # 抖音 API 服务
│   │   └── wework.js          # 企微 API 服务
│   ├── routes/
│   │   └── index.js           # 路由处理
│   └── utils/
│       ├── logger.js          # 日志工具
│       └── douyin-signature.js # 签名验证
├── web/
│   ├── index.html             # 管理后台页面
│   ├── style.css              # 样式文件
│   └── app.js                 # 前端逻辑
├── .env.example               # 环境变量模板
├── package.json               # 项目依赖
├── QUICK_START.md             # 快速部署指南
└── README.md                  # 项目说明
```

## 🔌 API 接口

### 健康检查
```
GET /api/health
```

### 抖音 Webhook 回调
```
POST /api/douyin/webhook
```

### 店铺授权回调
```
GET /api/douyin/callback
```

### 店铺管理
```
GET  /api/admin/shops                        # 获取店铺列表
POST /api/admin/shops/:shopId/wework-chat    # 配置企微群
```

### 消息日志
```
GET /api/admin/logs                          # 获取消息日志
GET /api/admin/statistics                    # 获取统计数据
```

### 测试接口
```
POST /api/test/push                          # 测试推送消息
```

## 🔐 环境变量说明

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `DOUYIN_CLIENT_KEY` | 抖音应用 Key | ✅ |
| `DOUYIN_CLIENT_SECRET` | 抖音应用 Secret | ✅ |
| `DOUYIN_SPI_TOKEN` | Webhook 验证 Token | ✅ |
| `WEWORK_CORP_ID` | 企业微信企业 ID | ✅ |
| `WEWORK_AGENT_ID` | 企业微信应用 ID | ✅ |
| `WEWORK_SECRET` | 企业微信应用 Secret | ✅ |
| `WEWORK_SENDER_USERID` | 发送者 UserID | ✅ |
| `DB_HOST` | 数据库主机 | ✅ |
| `DB_PORT` | 数据库端口 | ❌ |
| `DB_USER` | 数据库用户名 | ✅ |
| `DB_PASSWORD` | 数据库密码 | ✅ |
| `DB_NAME` | 数据库名称 | ✅ |
| `PORT` | 服务端口 | ❌ |
| `NODE_ENV` | 运行环境 | ❌ |

## 📝 开发指南

### 本地开发

```bash
# 安装依赖
npm install

# 启动开发服务器(带热重载)
npm run dev

# 查看日志
tail -f logs/app.log
```

### 代码规范

- 使用 ES6+ 语法
- 函数和类添加 JSDoc 注释
- 错误处理使用 try-catch
- 日志使用统一的 logger 模块

## 🧪 测试

### 测试 Webhook

```bash
curl -X POST http://localhost:3000/api/douyin/webhook \
  -H "Content-Type: application/json" \
  -H "X-Douyin-Signature: your-signature" \
  -d '{"type":"order_new","data":{"shop_id":"123"}}'
```

### 测试推送

在管理后台的 "Webhook 测试" 页面进行可视化测试。

## 🐛 故障排查

### 常见问题

1. **数据库连接失败**
   - 检查 MySQL 是否运行
   - 验证数据库配置是否正确
   - 确认数据库已创建

2. **Webhook 接收不到消息**
   - 确认服务器可公网访问
   - 检查 HTTPS 配置
   - 验证签名 Token 配置

3. **企微推送失败**
   - 检查 CorpID 和 Secret 是否正确
   - 确认发送者在应用可见范围
   - 验证 Chat ID 是否正确

### 日志查看

```bash
# 应用日志
tail -f logs/app.log

# PM2 日志
pm2 logs beauty-notification
```

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request!

## 📞 联系方式

- Issues: <your-repo-url>/issues
- 文档: [快速部署指南](./QUICK_START.md)

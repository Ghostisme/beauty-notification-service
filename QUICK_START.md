# 快速部署指南

## 🚀 快速开始

### 1. 环境要求

- **Node.js**: 16.x 或更高版本
- **MySQL**: 5.7 或更高版本
- **域名**: 需要一个可公网访问的域名(用于接收抖音回调)
- **HTTPS**: 生产环境必须使用 HTTPS

### 2. 克隆代码

```bash
git clone <your-repo-url>
cd beauty-notification-service
```

### 3. 安装依赖

```bash
npm install
```

### 4. 配置环境变量

复制配置文件模板:

```bash
cp .env.example .env
```

编辑 `.env` 文件,填入以下配置:

```env
# ========================================
# 抖音生活服务配置
# ========================================
DOUYIN_CLIENT_KEY=你的Client_Key
DOUYIN_CLIENT_SECRET=你的Client_Secret
DOUYIN_SPI_TOKEN=your_random_token_here

# ========================================
# 企业微信配置
# ========================================
WEWORK_CORP_ID=企业ID
WEWORK_AGENT_ID=应用ID
WEWORK_SECRET=应用Secret
WEWORK_SENDER_USERID=员工账号

# ========================================
# 数据库配置
# ========================================
DB_HOST=localhost
DB_PORT=3306
DB_USER=beauty_user
DB_PASSWORD=数据库密码
DB_NAME=beauty_notification

# ========================================
# 服务器配置
# ========================================
PORT=3000
NODE_ENV=production
```

### 5. 创建数据库

```sql
CREATE DATABASE beauty_notification CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 可选: 创建专用用户
CREATE USER 'beauty_user'@'localhost' IDENTIFIED BY '你的密码';
GRANT ALL PRIVILEGES ON beauty_notification.* TO 'beauty_user'@'localhost';
FLUSH PRIVILEGES;
```

### 6. 启动服务

```bash
# 生产环境
npm start

# 开发环境
npm run dev
```

### 7. 访问管理后台

打开浏览器访问:

```
http://localhost:3000/admin/dashboard/
```

## 📡 抖音配置

### 1. 在抖音开放平台配置 Webhook

登录 [抖音开放平台](https://open.douyin.com/),进入你的应用:

1. **Webhook 回调地址**:
   ```
   https://your-domain.com/api/douyin/webhook
   ```

2. **SPI Token**: 使用 `.env` 中配置的 `DOUYIN_SPI_TOKEN`

3. **订阅事件**: 勾选需要接收的消息类型

### 2. 配置授权回调地址

在应用配置中添加授权回调地址:

```
https://your-domain.com/api/douyin/callback
```

### 3. 授权店铺

1. 在管理后台点击 "授权新店铺"
2. 复制授权链接并在浏览器打开
3. 完成抖音账号授权
4. 授权成功后会自动跳转回系统

## 👥 企业微信配置

### 1. 创建企业微信应用

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/)
2. 应用管理 → 创建应用
3. 记录 **AgentId** 和 **Secret**

### 2. 配置可见范围

确保发送者员工在应用的可见范围内

### 3. 绑定企微群

1. 在管理后台的 "店铺管理" 页面
2. 点击 "配置企微群"
3. 输入客户群的 Chat ID

### 获取 Chat ID

使用企业微信 API 获取外部客户群列表:

```bash
# 获取 access_token
curl "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=YOUR_CORP_ID&corpsecret=YOUR_SECRET"

# 获取群列表
curl "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/groupchat/list?access_token=ACCESS_TOKEN"
```

## 🐳 Docker 部署 (可选)

使用 Docker Compose 快速部署:

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 🔧 生产环境部署建议

### 1. 使用 PM2 管理进程

```bash
# 安装 PM2
npm install -g pm2

# 启动应用
pm2 start src/server.js --name beauty-notification

# 设置开机自启
pm2 startup
pm2 save

# 查看日志
pm2 logs beauty-notification

# 重启应用
pm2 restart beauty-notification
```

### 2. 使用 Nginx 反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 重定向到 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
}
```

### 3. 配置 HTTPS

使用 Let's Encrypt 免费证书:

```bash
# 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com
```

## 🧪 测试部署

### 1. 测试健康检查

```bash
curl http://localhost:3000/api/health
```

预期输出:
```json
{
  "status": "ok",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "service": "beauty-notification-service"
}
```

### 2. 测试 Webhook

在管理后台的 "Webhook 测试" 页面:

1. 选择已授权的店铺
2. 输入测试消息
3. 点击 "发送测试"
4. 检查企微群是否收到消息

## 📊 监控和日志

### 查看应用日志

```bash
# PM2 日志
pm2 logs beauty-notification

# 或直接查看日志文件
tail -f logs/app.log
```

### 监控指标

在管理后台查看:

- 已授权店铺数
- 今日消息数
- 推送成功率
- 累计客户数

## 🔐 安全建议

1. **定期更新依赖**: `npm update`
2. **使用强密码**: 数据库密码、Token 等
3. **启用防火墙**: 只开放必要端口
4. **定期备份数据库**
5. **监控异常日志**

## ❓ 常见问题

### 1. Webhook 收不到消息

- 检查域名是否可公网访问
- 确认 HTTPS 证书有效
- 验证 SPI Token 配置正确
- 查看服务器日志

### 2. 推送到企微失败

- 确认 CorpID、Secret 配置正确
- 检查发送者是否在应用可见范围
- 验证 Chat ID 是否正确
- 查看企微 API 返回的错误信息

### 3. Token 过期

系统会自动刷新 Token,如遇问题:

- 检查数据库中的 token_expires_at 字段
- 重新授权店铺

## 📞 技术支持

遇到问题请查看:

- [抖音开放平台文档](https://developer.open-douyin.com/)
- [企业微信 API 文档](https://developer.work.weixin.qq.com/document/)
- 项目 Issues: <your-repo-url>/issues

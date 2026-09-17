# 生产环境部署文档

## 📋 部署架构

```
┌─────────────┐
│   浏览器     │
└──────┬──────┘
       │ HTTPS
       ↓
┌─────────────────┐
│     Nginx       │ ← 静态文件 + 反向代理
│  (端口 80/443)  │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│   Node.js App   │ ← PM2 管理
│   (端口 3000)   │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│     MySQL       │
│   (端口 3306)   │
└─────────────────┘
```

## 🚀 自动化部署

### 使用部署脚本 (推荐)

```bash
# 1. 上传代码到服务器
git clone <your-repo-url>
cd beauty-notification-service

# 2. 编辑域名配置
nano deploy-production.sh
# 修改 DOMAIN="your-domain.com" 为你的实际域名

# 3. 运行部署脚本
chmod +x deploy-production.sh
sudo ./deploy-production.sh
```

脚本会自动完成:
- ✅ 安装 NVM 和 Node.js 18
- ✅ 安装 PM2 进程管理器
- ✅ 安装和配置 Nginx
- ✅ 复制项目文件到 `/var/www/beauty-notification`
- ✅ 安装项目依赖
- ✅ 配置 Nginx 反向代理和静态文件服务
- ✅ 启动应用并设置开机自启
- ✅ 可选: 配置 Let's Encrypt SSL 证书

## 🛠️ 手动部署步骤

### 1. 准备服务器环境

```bash
# 更新系统
sudo apt update
sudo apt upgrade -y

# 安装基础工具
sudo apt install -y curl git build-essential
```

### 2. 安装 NVM 和 Node.js

```bash
# 安装 NVM
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

# 重新加载配置
source ~/.bashrc

# 安装 Node.js 18
nvm install 18
nvm use 18
nvm alias default 18

# 验证安装
node -v
npm -v
```

### 3. 安装 PM2

```bash
npm install -g pm2

# 验证安装
pm2 -v
```

### 4. 安装 Nginx

```bash
sudo apt install -y nginx

# 启动 Nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# 验证安装
nginx -v
```

### 5. 安装 MySQL

```bash
sudo apt install -y mysql-server

# 安全配置
sudo mysql_secure_installation

# 创建数据库
sudo mysql -u root -p
```

```sql
CREATE DATABASE beauty_notification CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'beauty_user'@'localhost' IDENTIFIED BY '你的密码';
GRANT ALL PRIVILEGES ON beauty_notification.* TO 'beauty_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 6. 部署项目代码

```bash
# 创建项目目录
sudo mkdir -p /var/www/beauty-notification
sudo chown -R $USER:$USER /var/www/beauty-notification

# 克隆代码
cd /var/www/beauty-notification
git clone <your-repo-url> .

# 安装依赖
npm install --production

# 配置环境变量
cp .env.example .env
nano .env
# 填写所有配置项
```

### 7. 配置 Nginx

```bash
# 复制配置文件
sudo cp nginx.conf /etc/nginx/sites-available/beauty-notification

# 编辑配置文件,修改域名
sudo nano /etc/nginx/sites-available/beauty-notification
# 将 your-domain.com 替换为实际域名

# 创建软链接
sudo ln -s /etc/nginx/sites-available/beauty-notification /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重载 Nginx
sudo systemctl reload nginx
```

### 8. 配置 SSL 证书

```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期测试
sudo certbot renew --dry-run
```

### 9. 启动应用

```bash
cd /var/www/beauty-notification

# 使用 PM2 启动
pm2 start ecosystem.config.js

# 查看状态
pm2 status

# 查看日志
pm2 logs beauty-notification

# 设置开机自启
pm2 startup systemd
pm2 save
```

## 📝 环境变量配置

编辑 `/var/www/beauty-notification/.env`:

```env
# 抖音配置
DOUYIN_CLIENT_KEY=你的Client_Key
DOUYIN_CLIENT_SECRET=你的Client_Secret
DOUYIN_SPI_TOKEN=随机生成的Token

# 企业微信配置
WEWORK_CORP_ID=企业ID
WEWORK_AGENT_ID=应用ID
WEWORK_SECRET=应用Secret
WEWORK_SENDER_USERID=员工UserID

# 数据库配置
DB_HOST=localhost
DB_PORT=3306
DB_USER=beauty_user
DB_PASSWORD=数据库密码
DB_NAME=beauty_notification

# 服务器配置
PORT=3000
NODE_ENV=production
```

## 🔧 常用管理命令

### PM2 进程管理

```bash
# 查看进程状态
pm2 status

# 查看实时日志
pm2 logs beauty-notification

# 重启应用
pm2 restart beauty-notification

# 停止应用
pm2 stop beauty-notification

# 删除进程
pm2 delete beauty-notification

# 查看监控面板
pm2 monit

# 保存进程列表
pm2 save

# 查看启动脚本
pm2 startup
```

### Nginx 管理

```bash
# 测试配置
sudo nginx -t

# 重载配置
sudo systemctl reload nginx

# 重启 Nginx
sudo systemctl restart nginx

# 查看状态
sudo systemctl status nginx

# 查看访问日志
sudo tail -f /var/log/nginx/beauty-notification-access.log

# 查看错误日志
sudo tail -f /var/log/nginx/beauty-notification-error.log
```

### 数据库管理

```bash
# 连接数据库
mysql -u beauty_user -p beauty_notification

# 备份数据库
mysqldump -u beauty_user -p beauty_notification > backup_$(date +%Y%m%d).sql

# 恢复数据库
mysql -u beauty_user -p beauty_notification < backup.sql
```

### Git 更新

```bash
cd /var/www/beauty-notification

# 拉取最新代码
git pull origin main

# 安装新依赖
npm install --production

# 重启应用
pm2 restart beauty-notification
```

## 🔐 安全加固

### 1. 配置防火墙

```bash
# 安装 UFW
sudo apt install -y ufw

# 允许 SSH
sudo ufw allow ssh

# 允许 HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 启用防火墙
sudo ufw enable

# 查看状态
sudo ufw status
```

### 2. 限制 SSH 访问

编辑 `/etc/ssh/sshd_config`:

```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

重启 SSH:
```bash
sudo systemctl restart sshd
```

### 3. 配置 fail2ban

```bash
sudo apt install -y fail2ban

sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

## 📊 监控和日志

### 应用日志

```bash
# PM2 日志
pm2 logs beauty-notification

# 应用日志目录
tail -f /var/www/beauty-notification/logs/app.log
```

### Nginx 日志

```bash
# 访问日志
tail -f /var/log/nginx/beauty-notification-access.log

# 错误日志
tail -f /var/log/nginx/beauty-notification-error.log
```

### 系统监控

```bash
# 实时监控
pm2 monit

# 系统资源
htop

# 磁盘使用
df -h

# 内存使用
free -h
```

## 🐛 故障排查

### 应用无法启动

```bash
# 检查端口占用
sudo lsof -i :3000

# 检查 PM2 日志
pm2 logs beauty-notification --err

# 检查环境变量
cat /var/www/beauty-notification/.env
```

### Nginx 502 错误

```bash
# 检查后端服务是否运行
pm2 status

# 检查 Nginx 错误日志
sudo tail -f /var/log/nginx/error.log

# 测试后端连接
curl http://localhost:3000/api/health
```

### 数据库连接失败

```bash
# 测试数据库连接
mysql -u beauty_user -p -h localhost beauty_notification

# 检查 MySQL 状态
sudo systemctl status mysql

# 查看 MySQL 错误日志
sudo tail -f /var/log/mysql/error.log
```

## 🔄 滚动更新流程

```bash
# 1. 备份数据库
mysqldump -u beauty_user -p beauty_notification > backup_$(date +%Y%m%d).sql

# 2. 拉取新代码
cd /var/www/beauty-notification
git pull origin main

# 3. 安装依赖
npm install --production

# 4. 重启应用(零停机)
pm2 reload beauty-notification

# 5. 验证
curl https://your-domain.com/api/health
```

## 📞 技术支持

遇到问题请查看:
- [快速部署指南](./QUICK_START.md)
- [项目文档](./README.md)
- 系统日志和错误信息

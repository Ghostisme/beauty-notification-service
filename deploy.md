# 🚀 服务器部署指南

## 第一步: 准备服务器环境

### 1. 安装 Node.js (如果还没安装)

```bash
# 使用 nvm 安装 Node.js 18 (推荐)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
source ~/.bashrc
nvm install 18
nvm use 18

# 或者直接安装
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs
```

### 2. 安装 PM2 (进程管理器)

```bash
npm install -g pm2
```

---

## 第二步: 上传代码到服务器

### 方法1: 使用 Git (推荐)

```bash
# 在服务器上
cd /var/www
git clone <你的仓库地址>
cd beauty-notification-service
```

### 方法2: 使用 FTP/SFTP 工具

使用 FileZilla、WinSCP 等工具,将整个项目文件夹上传到服务器的 `/var/www/beauty-notification-service/`

---

## 第三步: 安装依赖

```bash
cd /var/www/beauty-notification-service
npm install
```

---

## 第四步: 配置环境变量

在服务器上创建 `.env` 文件:

```bash
nano .env
```

填入以下内容(替换成你的真实配置):

```env
# 抖音配置
DOUYIN_CLIENT_KEY=awpfkyooscrnko9e
DOUYIN_CLIENT_SECRET=8f6574a4313cf6aaf7038cfc6c8123f0

# 服务器配置
SERVER_PORT=3000
SERVER_ENV=production

# 数据库配置 (如果需要)
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=你的数据库密码
DB_NAME=beauty_notification

# 企业微信配置 (后面配置)
WEWORK_CORP_ID=
WEWORK_AGENT_ID=
WEWORK_SECRET=
```

保存并退出 (Ctrl+X, 然后 Y, 然后 Enter)

---

## 第五步: 配置 Nginx 反向代理

### 1. 安装 Nginx

```bash
sudo apt update
sudo apt install nginx
```

### 2. 配置 SSL 证书 (Let's Encrypt 免费证书)

```bash
# 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d www.hongquanquan.cn -d hongquanquan.cn

# 测试自动续期
sudo certbot renew --dry-run
```

### 3. 配置 Nginx 站点

```bash
sudo nano /etc/nginx/sites-available/beauty-notification
```

粘贴以下配置:

```nginx
server {
    listen 80;
    server_name www.hongquanquan.cn hongquanquan.cn;
    
    # 自动跳转到 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name www.hongquanquan.cn hongquanquan.cn;

    # SSL 证书配置 (certbot 会自动添加)
    ssl_certificate /etc/letsencrypt/live/www.hongquanquan.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/www.hongquanquan.cn/privkey.pem;

    # SSL 安全配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;

    # 反向代理到 Node.js 应用
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
        
        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # 日志
    access_log /var/log/nginx/beauty-notification-access.log;
    error_log /var/log/nginx/beauty-notification-error.log;
}
```

### 4. 启用站点并重启 Nginx

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/beauty-notification /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
```

---

## 第六步: 启动应用

### 使用 PM2 启动

```bash
cd /var/www/beauty-notification-service

# 启动应用
pm2 start src/server.js --name beauty-notification

# 查看状态
pm2 status

# 查看日志
pm2 logs beauty-notification

# 设置开机自启
pm2 startup
pm2 save
```

---

## 第七步: 验证部署

### 1. 检查服务是否运行

```bash
# 检查端口
netstat -tlnp | grep 3000

# 查看 PM2 状态
pm2 status

# 查看日志
pm2 logs beauty-notification --lines 50
```

### 2. 测试 HTTPS 访问

在浏览器访问:
```
https://www.hongquanquan.cn
```

应该能看到你的服务主页。

### 3. 测试 Webhook 接口

```bash
curl -X POST https://www.hongquanquan.cn/api/douyin/webhook \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'
```

---

## 第八步: 防火墙配置

### 开放必要端口

```bash
# 如果使用 ufw
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 22/tcp
sudo ufw enable

# 如果使用 firewalld
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

---

## 🎯 完成部署后

现在可以回到抖音开放平台,填写 Webhook 地址:

```
https://www.hongquanquan.cn/api/douyin/webhook
```

应该就能成功配置了!

---

## 📋 常用 PM2 命令

```bash
# 查看应用列表
pm2 list

# 查看日志
pm2 logs beauty-notification

# 重启应用
pm2 restart beauty-notification

# 停止应用
pm2 stop beauty-notification

# 删除应用
pm2 delete beauty-notification

# 查看监控
pm2 monit
```

---

## 🔍 故障排查

### 1. 如果访问不了 HTTPS

检查 SSL 证书:
```bash
sudo certbot certificates
```

重新申请证书:
```bash
sudo certbot --nginx -d www.hongquanquan.cn -d hongquanquan.cn --force-renewal
```

### 2. 如果 Webhook 返回 404

检查 Nginx 日志:
```bash
sudo tail -f /var/log/nginx/beauty-notification-error.log
```

检查应用日志:
```bash
pm2 logs beauty-notification
```

### 3. 如果应用启动失败

查看详细错误:
```bash
pm2 logs beauty-notification --err
```

检查端口占用:
```bash
netstat -tlnp | grep 3000
```

---

## ✅ 检查清单

部署完成前,确认以下所有项:

- [ ] Node.js 已安装 (node -v)
- [ ] PM2 已安装 (pm2 -v)
- [ ] 代码已上传到服务器
- [ ] npm install 已完成
- [ ] .env 文件已配置
- [ ] SSL 证书已配置 (https:// 可以访问)
- [ ] Nginx 已配置反向代理
- [ ] 防火墙已开放 80、443 端口
- [ ] 应用已用 PM2 启动
- [ ] https://www.hongquanquan.cn 能访问
- [ ] Webhook 接口能收到请求

全部完成后,就可以在抖音开放平台配置 Webhook 地址了!

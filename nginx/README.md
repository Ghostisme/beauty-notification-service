# Nginx 配置说明

## 📁 配置文件结构

```
nginx/
├── nginx.conf                              # 主配置文件
├── conf.d/
│   ├── beauty-notification.conf           # 当前项目配置(生产可用)
│   └── future-frontend.conf.example       # 前后端分离示例(未来扩展)
├── ssl/                                    # SSL 证书目录
│   ├── your-domain.com.crt
│   └── your-domain.com.key
└── README.md                               # 本文件
```

## 🚀 快速部署

### 1. 安装 Nginx

```bash
# CentOS/RHEL
sudo yum install nginx -y

# Ubuntu/Debian
sudo apt install nginx -y
```

### 2. 部署配置文件

```bash
# 备份原配置
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup

# 复制新配置
sudo cp nginx/nginx.conf /etc/nginx/nginx.conf
sudo cp nginx/conf.d/beauty-notification.conf /etc/nginx/conf.d/

# 创建 SSL 证书目录
sudo mkdir -p /etc/nginx/ssl
```

### 3. 修改配置

编辑 `/etc/nginx/conf.d/beauty-notification.conf`:

```bash
sudo vi /etc/nginx/conf.d/beauty-notification.conf
```

修改以下内容:
- `server_name`: 改为你的实际域名
- `ssl_certificate`: SSL 证书路径
- `ssl_certificate_key`: SSL 私钥路径

### 4. 获取 SSL 证书

#### 方式 A: Let's Encrypt (免费,推荐)

```bash
# 安装 Certbot
sudo yum install certbot python3-certbot-nginx -y

# 获取证书(自动配置)
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# 测试自动续期
sudo certbot renew --dry-run
```

#### 方式 B: 阿里云/腾讯云证书

1. 在云服务商控制台申请免费 SSL 证书
2. 下载 Nginx 格式证书
3. 上传到服务器:

```bash
# 上传证书文件
sudo cp your-domain.com.crt /etc/nginx/ssl/
sudo cp your-domain.com.key /etc/nginx/ssl/

# 设置权限
sudo chmod 600 /etc/nginx/ssl/your-domain.com.key
sudo chown root:root /etc/nginx/ssl/*
```

### 5. 测试并启动

```bash
# 测试配置
sudo nginx -t

# 启动 Nginx
sudo systemctl start nginx

# 设置开机自启
sudo systemctl enable nginx

# 重载配置(修改后)
sudo systemctl reload nginx
```

## 🔧 当前架构说明

### 当前模式: 单体应用 + 简单管理后台

```
用户请求
    ↓
  Nginx (443)
    ↓
  反向代理
    ↓
  Node.js (3000)
    ↓
  Express 路由
    ├── /              → 首页
    ├── /api/          → API 接口
    ├── /admin/        → 管理后台(后端渲染)
    └── /test/         → 测试接口
```

**特点:**
- 简单直接,适合当前规模
- 所有请求通过 Nginx 反向代理到 Node.js
- 管理后台由 Node.js 服务静态文件

## 🎯 未来扩展架构

### 未来模式: 前后端分离

```
用户请求
    ↓
  Nginx (443)
    ├── app.your-domain.com    → 前端应用(Vue/React)
    │   ├── / (静态文件)         → Nginx 直接服务
    │   └── /api/*               → 反向代理到 Node.js
    │
    ├── admin.your-domain.com  → 管理后台前端
    │   ├── / (静态文件)         → Nginx 直接服务
    │   └── /admin/*             → 反向代理到 Node.js
    │
    └── api.your-domain.com    → 纯 API 服务
        └── /*                   → Node.js 后端
```

**优势:**
- 前端静态文件由 Nginx 直接服务,性能更好
- 前后端独立部署,职责清晰
- 可以使用 CDN 加速静态资源
- 支持多个前端应用共享同一后端

**迁移步骤(未来):**
1. 重命名 `future-frontend.conf.example` → `future-frontend.conf`
2. 修改域名和路径配置
3. 部署前端构建产物到指定目录
4. 重载 Nginx 配置

## 📊 配置功能说明

### 1. 性能优化

- **HTTP/2**: 多路复用,提升加载速度
- **Gzip 压缩**: 减少传输体积
- **连接池**: `keepalive 32` 复用上游连接
- **负载均衡**: `least_conn` 最少连接算法

### 2. 安全防护

- **HTTPS 强制**: HTTP 自动跳转 HTTPS
- **安全头**: HSTS、XSS 防护、防点击劫持
- **限流保护**:
  - API: 10 req/s,突发 20
  - Webhook: 5 req/s,突发 10
- **IP 白名单**: 管理后台可选启用

### 3. 日志监控

- **访问日志**: 包含响应时间、上游信息
- **错误日志**: warn 级别,便于排查
- **健康检查**: 不记录日志,避免刷屏

## 🔍 常用操作

### 查看日志

```bash
# 访问日志
sudo tail -f /var/log/nginx/beauty-notification.access.log

# 错误日志
sudo tail -f /var/log/nginx/beauty-notification.error.log

# 实时查看(带颜色)
sudo tail -f /var/log/nginx/access.log | grep --line-buffered "POST"
```

### 性能测试

```bash
# 测试并发性能
ab -n 1000 -c 10 https://your-domain.com/api/health

# 测试限流
ab -n 100 -c 20 https://your-domain.com/api/douyin/webhook
```

### 配置调优

```bash
# 查看当前连接数
sudo netstat -antp | grep nginx | wc -l

# 查看上游状态
curl -s http://localhost/api/health

# 验证 SSL 证书
openssl s_client -connect your-domain.com:443 -servername your-domain.com
```

## ⚠️ 注意事项

1. **生产环境**:
   - 务必配置 HTTPS,抖音 Webhook 要求必须 HTTPS
   - 建议启用管理后台 IP 白名单
   - 关闭或限制 `/test/` 测试接口

2. **证书更新**:
   - Let's Encrypt 证书 90 天过期
   - Certbot 会自动续期,确保 cron 任务正常

3. **防火墙**:
   ```bash
   # 开放端口
   sudo firewall-cmd --permanent --add-service=http
   sudo firewall-cmd --permanent --add-service=https
   sudo firewall-cmd --reload
   ```

4. **SELinux**(CentOS):
   ```bash
   # 允许 Nginx 连接网络
   sudo setsebool -P httpd_can_network_connect 1
   ```

## 📝 配置修改后的标准流程

```bash
# 1. 测试配置
sudo nginx -t

# 2. 如果测试通过,重载配置
sudo systemctl reload nginx

# 3. 查看日志确认
sudo tail -f /var/log/nginx/error.log
```

## 🆘 故障排查

### Nginx 启动失败

```bash
# 查看详细错误
sudo nginx -t
sudo journalctl -xe -u nginx
```

### 502 Bad Gateway

```bash
# 检查 Node.js 服务是否运行
pm2 status

# 检查端口是否监听
sudo netstat -tlnp | grep 3000

# 查看 Nginx 错误日志
sudo tail -f /var/log/nginx/error.log
```

### SSL 证书问题

```bash
# 检查证书有效期
openssl x509 -in /etc/nginx/ssl/your-domain.com.crt -noout -dates

# 检查证书链
openssl s_client -connect your-domain.com:443 -servername your-domain.com
```

## 📚 参考资源

- [Nginx 官方文档](http://nginx.org/en/docs/)
- [Let's Encrypt 文档](https://letsencrypt.org/docs/)
- [SSL Labs 测试](https://www.ssllabs.com/ssltest/)
- [HTTP/2 测试](https://tools.keycdn.com/http2-test)

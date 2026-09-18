#!/bin/bash

# 修复 Nginx 配置 - /admin 路由冲突问题
# 问题: /admin 被配置为静态文件服务,导致 API 路由无法访问

echo "🔧 修复 Nginx 配置..."

cat > /etc/nginx/sites-available/beauty-notification << 'EOF'
server {
    listen 80;
    server_name notification.hongquanquan.cn;

    # HTTP 重定向到 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name notification.hongquanquan.cn;

    # SSL 证书配置
    ssl_certificate /etc/letsencrypt/live/notification.hongquanquan.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/notification.hongquanquan.cn/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # 日志配置
    access_log /var/log/nginx/beauty-notification-access.log;
    error_log /var/log/nginx/beauty-notification-error.log;

    # 管理后台静态文件 (必须放在 API 路由之前,且路径要更具体)
    location = /admin {
        return 301 /admin/;
    }

    location /admin/ {
        alias /var/www/beauty-notification/web/;
        try_files $uri $uri/ /admin/index.html;

        # 静态文件缓存
        location ~* \.(css|js|jpg|jpeg|png|gif|ico|svg|woff|woff2|ttf)$ {
            expires 7d;
            add_header Cache-Control "public, immutable";
        }
    }

    # API 路由 (所有以 /api 或 /admin/xxx 开头的 API 请求)
    # 注意: /admin/shops, /admin/logs 等 API 需要代理到后端
    location ~ ^/(api|test|admin/(shops|logs|statistics|wework)) {
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

    # 根路径
    location = / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

echo "✅ Nginx 配置已更新"

# 测试配置
echo ""
echo "🧪 测试 Nginx 配置..."
nginx -t

if [ $? -eq 0 ]; then
    echo ""
    echo "🔄 重载 Nginx..."
    systemctl reload nginx

    echo ""
    echo "✅ Nginx 重载成功!"
    echo ""
    echo "📋 测试 API 访问:"
    echo "curl -s https://notification.hongquanquan.cn/api/health"
    curl -s https://notification.hongquanquan.cn/api/health | python3 -m json.tool || echo "(需要安装 python3)"

    echo ""
    echo "curl -s https://notification.hongquanquan.cn/admin/shops"
    curl -s https://notification.hongquanquan.cn/admin/shops
else
    echo "❌ Nginx 配置测试失败,请检查错误"
    exit 1
fi

echo ""
echo "✅ 修复完成!"
echo "现在访问 https://notification.hongquanquan.cn/admin/ 应该可以正常加载数据了"

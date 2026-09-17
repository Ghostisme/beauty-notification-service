# Git 部署指南

本文档说明如何使用 Git 拉取代码的方式部署本项目。

## 🚀 一键部署

### 方式一: 使用部署脚本(推荐)

在服务器上执行:

```bash
curl -fsSL https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-git.sh | sudo bash
```

脚本会自动完成:
- ✅ 安装 Git、NVM、Node.js、PM2
- ✅ 克隆代码仓库
- ✅ 安装项目依赖
- ✅ 配置环境变量
- ✅ 启动应用并设置开机自启
- ✅ 可选配置 Nginx 和 SSL

### 方式二: 手动部署

```bash
# 1. 克隆代码
git clone https://github.com/Ghostisme/beauty-notification-service.git
cd beauty-notification-service

# 2. 配置环境
cp .env.example .env
nano .env  # 编辑配置

# 3. 安装依赖
npm install --production

# 4. 启动应用
pm2 start ecosystem.config.js
pm2 save
```

## 🔄 更新代码

### 方式一: 使用更新脚本

```bash
cd /var/www/beauty-notification
bash update.sh
```

### 方式二: 手动更新

```bash
cd /var/www/beauty-notification

# 拉取最新代码
git pull origin main

# 安装新依赖
npm install --production

# 重启应用
pm2 reload beauty-notification
```

## 📂 目录结构

```
/var/www/beauty-notification/     # 项目根目录
├── .git/                          # Git 仓库
├── .env                           # 环境配置(不会被覆盖)
├── src/                           # 源代码
├── web/                           # 前端页面
├── data/                          # 数据文件(JSON 模式)
├── logs/                          # 日志文件
├── node_modules/                  # 依赖包
└── ecosystem.config.js            # PM2 配置
```

## 🔐 .env 文件保护

更新时 `.env` 文件不会被覆盖:
- Git 中已忽略 `.env` 文件
- 更新脚本会自动备份并恢复 `.env`
- 敏感配置安全可靠

## 🌿 分支管理

### 主分支
```bash
git pull origin main
```

### 开发分支(如果有)
```bash
git checkout develop
git pull origin develop
```

### 创建本地测试分支
```bash
git checkout -b test-feature
# 测试完成后
git checkout main
git branch -D test-feature
```

## 🔍 查看版本信息

```bash
# 查看当前版本
cd /var/www/beauty-notification
git log -1 --oneline

# 查看所有提交
git log --oneline -10

# 查看文件变更
git status
```

## 🔄 回滚到指定版本

```bash
cd /var/www/beauty-notification

# 查看提交历史
git log --oneline

# 回滚到指定 commit
git reset --hard <commit-hash>

# 重启应用
pm2 reload beauty-notification
```

## 🐛 故障排查

### 代码拉取失败

```bash
# 检查 Git 配置
git config --list

# 重新克隆
cd /var/www
rm -rf beauty-notification
git clone https://github.com/Ghostisme/beauty-notification-service.git beauty-notification
```

### 依赖安装失败

```bash
# 清除缓存
npm cache clean --force

# 删除 node_modules 重新安装
rm -rf node_modules package-lock.json
npm install --production
```

### PM2 进程未启动

```bash
# 查看错误日志
pm2 logs beauty-notification --err

# 删除进程重新启动
pm2 delete beauty-notification
pm2 start ecosystem.config.js
```

## 📝 常用命令

### Git 操作

```bash
# 查看远程地址
git remote -v

# 切换分支
git checkout <branch-name>

# 拉取指定分支
git pull origin <branch-name>

# 放弃本地修改
git reset --hard HEAD
git clean -fd
```

### PM2 操作

```bash
# 查看进程
pm2 list

# 查看日志
pm2 logs beauty-notification

# 重启
pm2 restart beauty-notification

# 停止
pm2 stop beauty-notification

# 删除
pm2 delete beauty-notification
```

### 系统操作

```bash
# 查看端口占用
sudo lsof -i :3000

# 查看磁盘空间
df -h

# 查看内存使用
free -h

# 查看 Node.js 版本
node -v
```

## 🔧 自动化部署

### 配置 GitHub Actions(可选)

在仓库中添加 `.github/workflows/deploy.yml`:

```yaml
name: Deploy

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to server
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          script: |
            cd /var/www/beauty-notification
            bash update.sh
```

### 配置 Webhook(可选)

在服务器上设置 webhook 监听:

```bash
# 安装 webhook
sudo apt install webhook

# 配置自动拉取
# 详见 GitHub Webhooks 文档
```

## 📦 数据备份

### 备份数据

```bash
# JSON 模式
tar -czf backup-$(date +%Y%m%d).tar.gz data/

# MySQL 模式
mysqldump -u beauty_user -p beauty_notification > backup-$(date +%Y%m%d).sql
```

### 恢复数据

```bash
# JSON 模式
tar -xzf backup-20240115.tar.gz

# MySQL 模式
mysql -u beauty_user -p beauty_notification < backup-20240115.sql
```

## 🎯 最佳实践

1. **定期拉取更新** - 每周检查一次代码更新
2. **备份数据** - 更新前备份数据库和配置文件
3. **查看日志** - 更新后检查应用日志确认正常
4. **测试功能** - 更新后测试关键功能
5. **监控性能** - 使用 `pm2 monit` 监控资源使用

## 📞 技术支持

- GitHub Issues: https://github.com/Ghostisme/beauty-notification-service/issues
- 部署文档: [DEPLOYMENT.md](./DEPLOYMENT.md)
- 快速开始: [QUICK_START.md](./QUICK_START.md)

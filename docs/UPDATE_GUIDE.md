# 更新指南

## 📋 智能更新脚本说明

更新脚本 `update.sh` 会自动检测和处理:

### ✨ 功能特性

1. **代码变更检测**
   - 自动对比更新前后的 Git 提交
   - 显示变更的文件列表
   - 展示提交日志

2. **依赖变化监控**
   - 检查 `package.json` 是否变化
   - 仅在依赖变化时重新安装
   - 节省更新时间

3. **智能重启策略**
   - 依赖变化: 完全重启 (`pm2 restart`)
   - 仅代码变化: 零停机热重载 (`pm2 reload`)

4. **配置文件保护**
   - 自动备份和恢复 `.env`
   - 避免配置被覆盖

5. **更新摘要**
   - 显示版本变化
   - 列出变更内容
   - 提供后续操作指引

## 🚀 使用方式

### 方式一: 执行更新脚本

```bash
cd /var/www/beauty-notification
bash update.sh
```

### 方式二: 监控更新

```bash
cd /var/www/beauty-notification
bash scripts/monitor-update.sh
```

会自动检查远程更新并询问是否执行。

## 📊 输出示例

```bash
=========================================
🔄 开始智能更新...
=========================================

📋 备份配置文件...
✅ 配置已备份

📊 检查当前状态...
  - 当前版本: 156d440
  - package.json: a1b2c3d

📥 拉取最新代码...
📝 变更摘要:
789abcd feat: 添加新功能
456efgh fix: 修复 bug

✅ 代码更新完成

🔍 分析变更内容...
📂 代码文件变更:
M       src/server.js
A       src/new-feature.js

✅ 依赖无变化,跳过安装

✅ 配置文件已恢复

⏭️  跳过依赖安装

♻️  重启应用...
✅ 应用已重载(零停机)

=========================================
✅ 更新完成!
=========================================

📊 更新摘要:
  - 版本: 156d440 → 789abcd
  - 代码: 已更新
  - 依赖: 无变化

📝 后续操作:
  - 查看日志: pm2 logs beauty-notification
  - 查看状态: pm2 status
  - 访问后台: https://notification.hongquanquan.cn/admin/dashboard/

=========================================
```

## 🔍 检测机制

### 代码变更检测

```bash
# 对比 Git 提交 hash
BEFORE_COMMIT=$(git rev-parse HEAD)
AFTER_COMMIT=$(git rev-parse HEAD)

# 显示变更文件
git diff --name-status $BEFORE_COMMIT $AFTER_COMMIT
```

### 依赖变化检测

```bash
# 对比 package.json 的 MD5 hash
BEFORE_HASH=$(md5sum package.json | awk '{print $1}')
AFTER_HASH=$(md5sum package.json | awk '{print $1}')

# 仅在 hash 不同时重新安装
if [ "$BEFORE_HASH" != "$AFTER_HASH" ]; then
    npm install --production
fi
```

## 📅 定时更新

### 使用 Cron 定时检查

编辑 crontab:

```bash
crontab -e
```

添加定时任务(每天凌晨 2 点检查):

```bash
0 2 * * * cd /var/www/beauty-notification && bash scripts/monitor-update.sh
```

### 使用 systemd Timer

创建 `/etc/systemd/system/beauty-update.service`:

```ini
[Unit]
Description=Beauty Notification Update Service

[Service]
Type=oneshot
WorkingDirectory=/var/www/beauty-notification
ExecStart=/bin/bash /var/www/beauty-notification/update.sh
User=root
```

创建 `/etc/systemd/system/beauty-update.timer`:

```ini
[Unit]
Description=Beauty Notification Update Timer

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

启用定时器:

```bash
systemctl enable beauty-update.timer
systemctl start beauty-update.timer
```

## 🔄 回滚操作

如果更新后出现问题,可以快速回滚:

```bash
cd /var/www/beauty-notification

# 查看提交历史
git log --oneline -10

# 回滚到指定版本
git reset --hard <commit-hash>

# 重启应用
pm2 restart beauty-notification
```

## 🐛 故障排查

### 更新失败

```bash
# 放弃本地修改
git reset --hard HEAD
git clean -fd

# 重新拉取
git pull origin main
```

### 依赖安装失败

```bash
# 清除缓存
npm cache clean --force

# 删除 node_modules
rm -rf node_modules package-lock.json

# 重新安装
npm install --production
```

### PM2 重启失败

```bash
# 查看错误日志
pm2 logs beauty-notification --err

# 删除进程
pm2 delete beauty-notification

# 重新启动
pm2 start ecosystem.config.js
```

## 📝 最佳实践

1. **更新前备份数据**
   ```bash
   # JSON 模式
   tar -czf backup-$(date +%Y%m%d).tar.gz data/
   
   # MySQL 模式
   mysqldump -u beauty_user -p beauty_notification > backup.sql
   ```

2. **测试环境验证**
   - 在测试环境先验证更新
   - 确认无问题后再更新生产环境

3. **监控日志**
   ```bash
   # 实时查看日志
   pm2 logs beauty-notification --lines 100
   ```

4. **检查服务状态**
   ```bash
   # 查看进程状态
   pm2 status
   
   # 查看资源使用
   pm2 monit
   ```

## 🔗 相关文档

- [Git 部署指南](../GIT_DEPLOY.md)
- [Git 加速配置](../GIT_ACCELERATION.md)
- [部署文档](../DEPLOYMENT.md)
- [快速开始](../快速部署指南.md)

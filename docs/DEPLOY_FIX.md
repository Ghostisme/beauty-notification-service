# 部署问题修复指南

## 问题: sudo bash 无法检测到 Node.js

### 原因
当使用 `curl | sudo bash` 部署时,sudo 会创建一个新的受限环境,无法访问:
- 用户的 NVM 环境变量
- 用户的 PATH 设置
- 通过 NVM 安装的 Node.js

### ✅ 解决方案 1: 先下载脚本再执行

```bash
# 1. 下载部署脚本
wget https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-git.sh

# 2. 添加执行权限
chmod +x deploy-git.sh

# 3. 切换到 root 执行(而不是 sudo bash)
sudo su -
./deploy-git.sh
```

或者一行命令:

```bash
wget https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-git.sh && chmod +x deploy-git.sh && sudo su - -c "$(pwd)/deploy-git.sh"
```

### ✅ 解决方案 2: 传递完整 PATH 给 sudo

```bash
curl -fsSL https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-git.sh | sudo env "PATH=$PATH" bash
```

### ✅ 解决方案 3: 创建 Node.js 符号链接(推荐)

如果你的 Node.js 安装在 NVM 目录,可以创建全局符号链接:

```bash
# 1. 找到 Node.js 的实际路径
which node
# 输出例如: /root/.nvm/versions/node/v20.6.0/bin/node

# 2. 创建符号链接到系统路径
sudo ln -s $(which node) /usr/local/bin/node
sudo ln -s $(which npm) /usr/local/bin/npm

# 3. 验证
sudo node -v  # 应该能正常输出版本号

# 4. 重新执行部署
curl -fsSL https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-git.sh | sudo bash
```

### ✅ 解决方案 4: 手动部署(最可靠)

如果自动脚本一直有问题,可以手动执行每一步:

```bash
# 1. 切换到 root
sudo su -

# 2. 克隆代码
cd /var/www
git clone https://github.com/Ghostisme/beauty-notification-service.git beauty-notification
cd beauty-notification

# 3. 配置环境变量
cp .env.example .env
nano .env  # 编辑配置

# 4. 安装依赖
npm install --production

# 5. 安装 PM2(如果未安装)
npm install -g pm2

# 6. 启动应用
pm2 start ecosystem.config.js

# 7. 设置开机自启
pm2 startup
pm2 save

# 8. 查看状态
pm2 status
pm2 logs beauty-notification
```

## 推荐的部署流程

### 第一次部署

```bash
# 1. 创建 Node.js 符号链接(只需要执行一次)
sudo ln -s $(which node) /usr/local/bin/node
sudo ln -s $(which npm) /usr/local/bin/npm

# 2. 验证
sudo node -v
sudo npm -v

# 3. 执行部署脚本
curl -fsSL https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-git.sh | sudo bash
```

### 后续更新

```bash
cd /var/www/beauty-notification
sudo bash update.sh
```

## 常见问题排查

### Q: 为什么 `node -v` 可以但 `sudo node -v` 不行?

A: 因为 Node.js 安装在用户目录的 NVM 中,sudo 切换到 root 环境后找不到这个路径。

### Q: 如何查看 Node.js 的实际安装路径?

```bash
which node
ls -la $(which node)
```

### Q: 如何验证 sudo 环境下能访问 Node.js?

```bash
sudo which node
sudo node -v
sudo npm -v
```

如果这些命令都能正常输出,说明环境配置正确。

### Q: PM2 也找不到怎么办?

```bash
# 1. 安装 PM2 到全局
sudo npm install -g pm2

# 2. 创建符号链接
sudo ln -s $(which pm2) /usr/local/bin/pm2

# 3. 验证
sudo pm2 -v
```

## 验证部署成功

```bash
# 1. 检查进程
pm2 status

# 2. 查看日志
pm2 logs beauty-notification

# 3. 测试 API
curl http://localhost:3000/api/health

# 4. 访问管理后台
# https://notification.hongquanquan.cn/admin/dashboard/
```

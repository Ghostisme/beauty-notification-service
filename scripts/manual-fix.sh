#!/bin/bash
# 手动修复 Node.js 路径 - 直接复制粘贴执行

echo "========================================="
echo "创建 Node.js/npm/PM2 符号链接"
echo "========================================="
echo ""

# 方式1: 如果你是 root 用户
echo "【方式1】如果你是 root 用户,直接执行:"
echo ""
echo "ln -sf \$(which node) /usr/local/bin/node"
echo "ln -sf \$(which npm) /usr/local/bin/npm"
echo "ln -sf \$(which pm2) /usr/local/bin/pm2"
echo ""

# 方式2: 如果你是普通用户
echo "【方式2】如果你是普通用户,执行:"
echo ""
echo "sudo ln -sf \$(which node) /usr/local/bin/node"
echo "sudo ln -sf \$(which npm) /usr/local/bin/npm"
echo "sudo ln -sf \$(which pm2) /usr/local/bin/pm2"
echo ""

# 验证
echo "【验证】执行完成后验证:"
echo ""
echo "sudo node -v"
echo "sudo npm -v"
echo "sudo pm2 -v"
echo ""

# 部署
echo "【部署】验证成功后执行部署:"
echo ""
echo "curl -fsSL https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/deploy-git.sh | sudo bash"
echo ""
echo "========================================="

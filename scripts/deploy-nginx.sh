#!/bin/bash
# ========================================
# Nginx 配置部署脚本
# ========================================
# 功能:
# 1. 自动备份当前配置
# 2. 部署新配置
# 3. 测试配置有效性
# 4. 安全重载 Nginx
# ========================================

set -e  # 遇到错误立即退出

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置路径
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NGINX_CONF_DIR="/etc/nginx"
BACKUP_DIR="/etc/nginx/backup"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Nginx 配置部署脚本${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}❌ 请使用 root 用户或 sudo 运行此脚本${NC}"
  exit 1
fi

# 检查 Nginx 是否已安装
if ! command -v nginx &> /dev/null; then
  echo -e "${RED}❌ Nginx 未安装,请先安装 Nginx${NC}"
  exit 1
fi

echo -e "${YELLOW}📁 项目目录: ${PROJECT_DIR}${NC}"
echo ""

# 创建备份目录
echo -e "${YELLOW}📦 创建备份目录...${NC}"
mkdir -p "$BACKUP_DIR"

# 备份当前配置
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
echo -e "${YELLOW}💾 备份当前配置...${NC}"
if [ -f "$NGINX_CONF_DIR/nginx.conf" ]; then
  cp "$NGINX_CONF_DIR/nginx.conf" "$BACKUP_DIR/nginx.conf.$TIMESTAMP"
  echo -e "${GREEN}✓ 已备份: $BACKUP_DIR/nginx.conf.$TIMESTAMP${NC}"
fi

if [ -d "$NGINX_CONF_DIR/conf.d" ]; then
  cp -r "$NGINX_CONF_DIR/conf.d" "$BACKUP_DIR/conf.d.$TIMESTAMP"
  echo -e "${GREEN}✓ 已备份: $BACKUP_DIR/conf.d.$TIMESTAMP${NC}"
fi
echo ""

# 创建必要的目录
echo -e "${YELLOW}📂 创建必要的目录...${NC}"
mkdir -p "$NGINX_CONF_DIR/ssl"
mkdir -p "$NGINX_CONF_DIR/conf.d"
mkdir -p "/var/www/certbot"
echo -e "${GREEN}✓ 目录已创建${NC}"
echo ""

# 部署配置文件
echo -e "${YELLOW}📋 部署配置文件...${NC}"
cp "$PROJECT_DIR/nginx/nginx.conf" "$NGINX_CONF_DIR/nginx.conf"
echo -e "${GREEN}✓ 已部署: nginx.conf${NC}"

cp "$PROJECT_DIR/nginx/conf.d/beauty-notification.conf" "$NGINX_CONF_DIR/conf.d/"
echo -e "${GREEN}✓ 已部署: beauty-notification.conf${NC}"
echo ""

# 提醒修改配置
echo -e "${YELLOW}⚠️  请确认以下配置项:${NC}"
echo -e "   1. 域名: ${NGINX_CONF_DIR}/conf.d/beauty-notification.conf"
echo -e "   2. SSL 证书路径"
echo -e "   3. 上游后端地址(默认 127.0.0.1:3000)"
echo ""

read -p "是否已修改配置? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo -e "${YELLOW}请先修改配置文件,然后重新运行此脚本${NC}"
  exit 0
fi

# 测试配置
echo -e "${YELLOW}🔍 测试 Nginx 配置...${NC}"
if nginx -t; then
  echo -e "${GREEN}✓ 配置测试通过${NC}"
  echo ""
else
  echo -e "${RED}❌ 配置测试失败,请检查配置文件${NC}"
  echo -e "${YELLOW}可以从备份恢复: $BACKUP_DIR${NC}"
  exit 1
fi

# 重载 Nginx
echo -e "${YELLOW}🔄 重载 Nginx...${NC}"
if systemctl reload nginx; then
  echo -e "${GREEN}✓ Nginx 已重载${NC}"
else
  echo -e "${RED}❌ Nginx 重载失败${NC}"
  exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✅ 部署成功!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}📝 后续步骤:${NC}"
echo -e "   1. 配置 SSL 证书(如果还没有)"
echo -e "      sudo certbot --nginx -d your-domain.com"
echo -e ""
echo -e "   2. 检查 Nginx 状态"
echo -e "      sudo systemctl status nginx"
echo -e ""
echo -e "   3. 查看日志"
echo -e "      sudo tail -f /var/log/nginx/beauty-notification.access.log"
echo ""
echo -e "${YELLOW}💡 提示:${NC}"
echo -e "   配置备份位置: $BACKUP_DIR"
echo -e "   如需回滚: cp $BACKUP_DIR/nginx.conf.$TIMESTAMP $NGINX_CONF_DIR/nginx.conf"
echo ""

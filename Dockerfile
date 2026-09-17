# 使用轻量级 Node.js 镜像
FROM node:18-alpine

# 设置工作目录
WORKDIR /app

# 设置时区为中国
RUN apk add --no-cache tzdata && \
    cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    apk del tzdata

# 复制 package 文件
COPY package*.json ./

# 安装生产依赖
RUN npm ci --only=production && \
    npm cache clean --force

# 复制源代码
COPY src/ ./src/

# 创建日志目录
RUN mkdir -p /app/logs && chmod 777 /app/logs

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', (r) => r.statusCode === 200 ? process.exit(0) : process.exit(1))"

# 暴露端口
EXPOSE 3000

# 非 root 用户运行（安全考虑）
USER node

# 启动服务
CMD ["node", "src/server.js"]

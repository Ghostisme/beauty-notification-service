# 后端 API 容器: web_admin.py 提供管理后台全部 /api
# 前端静态页(web/)由宿主机全局 nginx 直接托管, 不打进镜像
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# pip 走阿里云源(国内服务器构建提速)
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=60
RUN pip install --no-cache-dir -r requirements.txt

COPY sync.py web_admin.py storage.py ./

# 数据目录: 订单文件 / SQLite / 日志 / 去重状态(挂载卷持久化)
RUN mkdir -p data/incoming data/processed state logs

# 时区改为北京时间, 保证订单时间/汇总标题正确
ENV TZ=Asia/Shanghai \
    ADMIN_HOST=0.0.0.0 \
    ADMIN_PORT=8787 \
    STATE_DIR=/app/state

EXPOSE 8787

CMD ["python", "web_admin.py"]

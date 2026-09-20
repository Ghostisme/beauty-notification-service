# 云端微信容器: 微信 Linux 官方客户端 + noVNC 远程桌面 + 中继脚本
# 目的: 让「普通微信号发群」整条链路跑在 Ubuntu 服务器上, 零备案 / 零企业认证
#
# 构建: docker compose build     (在 deploy/wechat 目录下)
# 镜像内已含: Xvfb 虚拟屏幕 + openbox + x11vnc + noVNC(浏览器访问)
#            微信 Linux 官方客户端(x86_64)
#            xdotool / xclip / ImageMagick / tesseract(中文 OCR, 用于发送前校验群名)
#            python3 + requests(跑 wx_relay_linux.py)
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    TZ=Asia/Shanghai \
    HOME=/data/home \
    DISPLAY=:99 \
    SCREEN_GEOMETRY=1280x800x24 \
    WECHAT_DEB_URL=https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_x86_64.deb

# ---- 基础工具链(虚拟显示 / 远程桌面 / 自动化 / 中文OCR / 中文字体) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils procps \
        locales tzdata \
        dbus-x11 desktop-file-utils \
        xvfb x11vnc openbox x11-utils xdotool xclip wmctrl \
        novnc websockify \
        imagemagick tesseract-ocr tesseract-ocr-chi-sim \
        fonts-noto-cjk fontconfig \
        python3 python3-requests \
    && sed -i 's/^# *zh_CN.UTF-8/zh_CN.UTF-8/' /etc/locale.gen \
    && locale-gen zh_CN.UTF-8 \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# ---- 安装微信 Linux 官方客户端(用 apt 装本地 deb, 自动补齐依赖) ----
RUN curl -fL --retry 3 --connect-timeout 20 -o /tmp/wechat.deb "$WECHAT_DEB_URL" \
    && apt-get update \
    && (apt-get install -y --no-install-recommends /tmp/wechat.deb || apt-get -f install -y) \
    && rm -f /tmp/wechat.deb \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# /data: 微信数据 + 截图 + 校准产物(持久化)
# /opt/relay: 中继脚本(由 compose 挂载宿主机文件, 改脚本不用重建镜像)
VOLUME ["/data"]
WORKDIR /opt/relay

# 6080 = noVNC 网页版远程桌面(仅映射到 127.0.0.1, 由宿主机 nginx 加密码反代)
EXPOSE 6080 5900

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

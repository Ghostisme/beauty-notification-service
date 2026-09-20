#!/usr/bin/env bash
# 云端微信容器入口: 拉起虚拟显示 + 远程桌面 + 微信客户端 + 中继脚本
set -uo pipefail

DISPLAY="${DISPLAY:-:99}"
export DISPLAY
SCREEN_GEOMETRY="${SCREEN_GEOMETRY:-1280x800x24}"
export HOME="${HOME:-/data/home}"
RELAY_SERVER="${RELAY_SERVER:-https://notification.hongquanquan.cn}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
RELAY_INTERVAL="${RELAY_INTERVAL:-60}"
RELAY_LIMIT="${RELAY_LIMIT:-3}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
VNC_PORT="${VNC_PORT:-5900}"
WX_SEARCH_CLICK="${WX_SEARCH_CLICK:-}"

log() { echo "[$(date '+%F %T')] $*"; }

mkdir -p "$HOME" /data/.config /data/screenshots /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

# ---- 1. D-Bus 会话(微信 Qt 客户端需要) ----
if command -v dbus-launch >/dev/null 2>&1; then
  eval "$(dbus-launch --sh-syntax)" 2>/dev/null || true
fi

# ---- 2. 虚拟屏幕 Xvfb ----
log "启动虚拟屏幕 Xvfb $DISPLAY ($SCREEN_GEOMETRY)"
Xvfb "$DISPLAY" -screen 0 "$SCREEN_GEOMETRY" -nolisten tcp -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
for i in $(seq 1 30); do
  xdotool getdisplaygeometry >/dev/null 2>&1 && break
  sleep 1
done
xdotool getdisplaygeometry >/dev/null 2>&1 || { log "Xvfb 启动失败, 日志:"; cat /tmp/xvfb.log; exit 1; }
log "虚拟屏幕就绪: $(xdotool getdisplaygeometry)"

# ---- 3. 窗口管理器(没有 WM 时窗口无法 activate/最大化) ----
openbox >/tmp/openbox.log 2>&1 &
sleep 1

# ---- 4. VNC + noVNC 网页远程桌面 ----
VNC_PASS_ARGS=(-nopw)
if [ -n "${VNC_PASSWORD:-}" ]; then
  mkdir -p "$HOME/.vnc"
  x11vnc -storepasswd "$VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null 2>&1
  VNC_PASS_ARGS=(-rfbauth "$HOME/.vnc/passwd")
fi
log "启动 x11vnc :$VNC_PORT"
x11vnc -display "$DISPLAY" -forever -shared -quiet -rfbport "$VNC_PORT" "${VNC_PASS_ARGS[@]}" >/tmp/x11vnc.log 2>&1 &

log "启动 noVNC :$NOVNC_PORT  →  浏览器访问 http://<服务器>:${NOVNC_PORT}/vnc.html"
websockify --web=/usr/share/novnc "$NOVNC_PORT" "localhost:$VNC_PORT" >/tmp/websockify.log 2>&1 &

# ---- 5. 定位并启动微信客户端 ----
find_wechat_bin() {
  local c
  for c in wechat weixin WeChat Weixin; do
    command -v "$c" >/dev/null 2>&1 && { command -v "$c"; return; }
  done
  for c in /opt/weixin/wechat /opt/WeChat/wechat /usr/lib/weixin/wechat \
           /usr/local/bin/wechat /opt/wechat/wechat; do
    [ -x "$c" ] && { echo "$c"; return; }
  done
  c="$(find /opt /usr/lib -maxdepth 4 -type f -name 'wechat*' -perm -u+x 2>/dev/null | head -n 1)"
  [ -n "$c" ] && echo "$c"
}
WECHAT_BIN="$(find_wechat_bin)"
if [ -z "$WECHAT_BIN" ]; then
  log "✘ 未找到微信客户端可执行文件, 容器内可用命令:"; compgen -c | grep -i -E 'wechat|weixin' | sort -u
else
  log "启动微信客户端: $WECHAT_BIN"
  (
    while true; do
      "$WECHAT_BIN" >/tmp/wechat.log 2>&1
      log "微信进程退出(code=$?), 5 秒后自动重启(登录态一般会保留)"
      sleep 5
    done
  ) &
fi

# ---- 6. 等微信主窗口出现并铺满屏幕 ----
(
  for i in $(seq 1 90); do
    WID="$(xdotool search --onlyvisible --name '微信' 2>/dev/null | head -n 1)"
    [ -z "$WID" ] && WID="$(xdotool search --onlyvisible --name 'WeChat' 2>/dev/null | head -n 1)"
    if [ -n "$WID" ]; then
      xdotool windowsize "$WID" 100% 100% 2>/dev/null
      xdotool windowmove "$WID" 0 0 2>/dev/null
      xdotool windowactivate --sync "$WID" 2>/dev/null
      log "微信窗口已就绪并最大化 (id=$WID)。若未登录, 请打开 noVNC 扫码。"
      break
    fi
    sleep 2
  done
) &

# ---- 7. 启动中继(把待发队列的消息发到微信群) ----
if [ -n "$ADMIN_TOKEN" ] && [ -f /opt/relay/wx_relay_linux.py ]; then
  log "启动中继: $RELAY_SERVER (每 ${RELAY_INTERVAL}s 取件, 每轮最多 ${RELAY_LIMIT} 条)"
  (
    sleep 15   # 给微信一点启动时间
    python3 /opt/relay/wx_relay_linux.py \
      --server "$RELAY_SERVER" \
      --token "$ADMIN_TOKEN" \
      --interval "$RELAY_INTERVAL" \
      --limit "$RELAY_LIMIT" \
      ${WX_SEARCH_CLICK:+--search-click "$WX_SEARCH_CLICK"} \
      ${RELAY_ARGS:-} >>/data/relay.log 2>&1
  ) &
else
  log "⚠ 未设置 ADMIN_TOKEN 或未挂载 wx_relay_linux.py, 中继未启动(仅提供云端微信)"
fi

log "容器就绪。noVNC: http://127.0.0.1:${NOVNC_PORT}/vnc.html   中继日志: /data/relay.log"

# ---- 8. 优雅退出 ----
term() {
  log "收到停止信号, 正在退出…"
  kill "$XVFB_PID" 2>/dev/null
  pkill -f x11vnc 2>/dev/null
  pkill -f websockify 2>/dev/null
  pkill -f wechat 2>/dev/null
  exit 0
}
trap term TERM INT

# 主进程保活: 任一关键进程挂掉就退出交给 Docker 重启策略
while true; do
  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    log "Xvfb 已退出, 容器结束"
    exit 1
  fi
  sleep 20
done

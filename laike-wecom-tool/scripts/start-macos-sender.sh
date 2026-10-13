#!/bin/bash
# Double-click entry points run this script in the logged-in user's Terminal.
set -euo pipefail

LAIKE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$LAIKE_ROOT"
export PYTHONUTF8=1

laike_finish() {
    laike_status=$?
    if [ "$laike_status" -ne 0 ]; then
        printf '\n发送端尚未就绪，请按上方提示处理后重试。\n'
    else
        printf '\n本次操作已结束。\n'
    fi
    if [ -t 0 ]; then
        read -r -p '按回车关闭此窗口…' laike_unused || true
    fi
}
trap laike_finish EXIT

if [ "$(uname -s)" != "Darwin" ]; then
    printf '此入口在 Mac 使用；Windows 请用 .bat 入口。\n'
    exit 2
fi

if [ ! -x .sender-venv/bin/python ]; then
    LAIKE_PYTHON="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12"
    if [ ! -x "$LAIKE_PYTHON" ]; then
        LAIKE_PYTHON="$(command -v python3.12 || true)"
    fi
    if [ -z "$LAIKE_PYTHON" ]; then
        printf '请先安装 python.org 的 Python 3.12 macOS universal2 安装包，再重试。\n'
        exit 2
    fi
    "$LAIKE_PYTHON" -m venv .sender-venv
fi
LAIKE_PYTHON="$LAIKE_ROOT/.sender-venv/bin/python"
"$LAIKE_PYTHON" -c 'import sys, tkinter; assert sys.version_info[:2] == (3,12), "请使用 Python 3.12"'
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || true)" = "1" ]; then
    "$LAIKE_PYTHON" -c 'import platform; assert platform.machine() == "arm64", "Apple 芯片请使用原生 ARM64 Python，并关闭终端的使用 Rosetta 打开选项"'
fi

# Subsequent launches compare the lock file; no repeated dependency downloads.
LAIKE_LOCK_SUM="$(/usr/bin/shasum -a 256 requirements-sender-macos.lock | /usr/bin/awk '{print $1}')"
LAIKE_INSTALLED_SUM="$(cat .sender-venv/.laike-lock-sha256 2>/dev/null || true)"
if [ "$LAIKE_LOCK_SUM" != "$LAIKE_INSTALLED_SUM" ]; then
    "$LAIKE_PYTHON" -m pip install --disable-pip-version-check -r requirements-sender-macos.lock
    printf '%s\n' "$LAIKE_LOCK_SUM" > .sender-venv/.laike-lock-sha256
fi

LAIKE_MODE="${1:-run}"
LAIKE_ARGS=(sender.py)
LAIKE_CONFIGURE_ARGS=(sender.py --configure)
if [ "$LAIKE_MODE" = "test" ]; then
    LAIKE_ARGS+=(--test-only)
    LAIKE_CONFIGURE_ARGS+=(--test-only)
fi
if [ ! -f sender-config.json ]; then
    "$LAIKE_PYTHON" "${LAIKE_CONFIGURE_ARGS[@]}"
fi
if [ "$LAIKE_MODE" = "groups" ]; then
    "$LAIKE_PYTHON" sender.py --groups
    exit 0
fi

"$LAIKE_PYTHON" sender.py --permissions
if [ "$LAIKE_MODE" = "calibrate" ]; then
    "$LAIKE_PYTHON" sender.py --calibrate
    exit 0
fi
if [ "$LAIKE_MODE" = "check" ]; then
    # Allow keyboard activity from launch to settle; this never claims a message.
    printf '检查连接中，请暂时停止鼠标键盘操作。\n'
    /bin/sleep 4
    "$LAIKE_PYTHON" sender.py --check
    exit 0
fi

LAIKE_PROFILE="$("$LAIKE_PYTHON" -c 'import json,pathlib; print(pathlib.Path(json.load(open("sender-config.json"))["profile"]).resolve())')"
if [ ! -f "$LAIKE_PROFILE" ] || ! "$LAIKE_PYTHON" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("platform") == "darwin" else 1)' "$LAIKE_PROFILE"; then
    "$LAIKE_PYTHON" sender.py --calibrate
fi
printf '\n发送端开始运行。保持企微登录、桌面解锁和窗口尺寸不变。\n'
printf '测试入口仅处理壹心-湖南-测试消息店；后台的自动发送开关决定是否发送。\n'
printf '关闭此窗口或按 Ctrl+C 可停止。此窗口运行期间会阻止自动休眠，但不能阻止手动锁屏或合盖。\n\n'
/usr/bin/caffeinate -di "$LAIKE_PYTHON" "${LAIKE_ARGS[@]}"

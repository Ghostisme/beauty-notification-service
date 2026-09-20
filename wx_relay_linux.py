# -*- coding: utf-8 -*-
"""
普通微信号中继 (Linux / 容器版) —— 零备案/零认证把消息发到微信群

与 wx_relay.py(Windows 版) 的区别:
  Windows 版用 wxauto 驱动微信 PC 客户端 (UIAutomation)。
  Linux 版没有 UIAutomation, 改为用 X11 自动化 (xdotool + xclip) 驱动
  「微信 Linux 官方客户端」, 全程走剪贴板粘贴, 不依赖中文输入法。

为什么需要它:
  个人微信号腾讯没有开放任何服务端接口。所谓"用普通微信号发群", 本质是
  在一台机器上开着微信客户端 + 模拟人工操作。把这台"机器"从你的 Windows
  电脑换成服务器上的 Docker 容器, 就可以 7x24 全自动, 完全绕开企业微信的
  企业认证 / 可信域名 / 可信IP / ICP备案 全部要求。
  代价: 属于客户端自动化操作, 违反《微信个人帐号使用规范》有账号风险,
        请务必使用小号、控制频率、不要发营销骚扰内容。

工作原理:
  服务器端把文案写进「待发队列」(outbox 表), 本脚本定时轮询:
      GET  /api/outbox?status=pending   → 取件
      微信客户端: Ctrl+F 搜索群名 → 回车打开会话 → 校验群名 → 粘贴发送
      POST /api/outbox/ack              → 回报(失败自动重试, 最多5次)

用法:
  python3 wx_relay_linux.py --server https://notification.hongquanquan.cn --token 你的ADMIN_TOKEN
  python3 wx_relay_linux.py --server ... --token ... --once        # 只跑一轮
  python3 wx_relay_linux.py --server ... --token ... --dry-run     # 只打印不发送
  python3 wx_relay_linux.py --check                                # 自检环境(推荐先跑)
  python3 wx_relay_linux.py --calibrate                            # 校准: 截图+窗口信息

前置条件:
  1. 容器内已启动微信并完成扫码登录(浏览器打开 noVNC 扫码)
  2. 目标群已存在于该微信号的会话列表(群名要与服务器配置完全一致)
  3. 微信窗口已铺满虚拟屏幕(entrypoint.sh 会自动最大化)
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

import requests

DEFAULT_SERVER = os.environ.get("RELAY_SERVER", "https://notification.hongquanquan.cn")
DEFAULT_TOKEN = os.environ.get("ADMIN_TOKEN", "")
DISPLAY = os.environ.get("DISPLAY", ":99")
# 发送前群名校验用的截图落盘位置(保留一份便于事后核对发到了哪个群)
VERIFY_SHOT = os.environ.get("WX_VERIFY_SHOT", "/data/screenshots/verify.png")

# 微信主窗口标题可能是其中之一
WINDOW_NAMES = ["微信", "WeChat", "wechat", "Weixin", "weixin", "Wechat"]

# 校验时对 OCR 结果的宽松度: 目标群名至少这么多比例的字要在截图里出现
VERIFY_HIT_RATIO = 0.6


def log(msg):
    print(time.strftime("[%Y-%m-%d %H:%M:%S]") + " " + str(msg), flush=True)


def _env():
    e = dict(os.environ)
    e["DISPLAY"] = DISPLAY
    return e


def sh(cmd, inp=None, check=True, timeout=30):
    """执行外部命令, 返回 stdout(str)。cmd 为 list。"""
    try:
        r = subprocess.run(cmd, input=inp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=_env(), timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError(f"命令不存在: {cmd[0]} (容器内应已安装, 请检查镜像构建)")
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败 {' '.join(cmd)}: {r.stderr.decode('utf-8', 'ignore').strip()[:300]}")
    return r.stdout.decode("utf-8", "ignore")


# ---------------- 可用性探测 ----------------

def _which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def check_env():
    """返回 (ok, 报告行列表)。容器启动后先跑这个, 少踩坑。"""
    lines, ok = [], True

    def add(name, good, extra=""):
        nonlocal ok
        ok = ok and good
        lines.append(f"{'✔' if good else '✘'} {name}{(' — ' + extra) if extra else ''}")

    add("DISPLAY 环境变量", bool(DISPLAY), DISPLAY)
    for tool in ("xdotool", "xclip"):
        add(f"工具 {tool}", bool(_which(tool)), _which(tool) or "未安装")
    add("工具 import(ImageMagick)", bool(_which("import", "magick")), "")
    add("工具 tesseract(OCR校验)", bool(_which("tesseract")), "缺失时跳过群名校验")
    add("X 服务可连接", _display_ok(), DISPLAY)
    wid = find_wechat_window(quiet=True)
    add("微信主窗口", bool(wid), f"window id={wid}" if wid else "未找到, 请先在 noVNC 里启动并登录微信")
    return ok, lines


def _display_ok():
    if not _which("xdotool"):
        return False
    try:
        sh(["xdotool", "getdisplaygeometry"], check=True, timeout=10)
        return True
    except Exception:
        return False


# ---------------- 窗口定位 ----------------

def _window_size(wid):
    try:
        out = sh(["xdotool", "getwindowgeometry", "--shell", str(wid)], check=False)
        w = h = 0
        for line in out.splitlines():
            if line.startswith("WIDTH="):
                w = int(line.split("=", 1)[1])
            elif line.startswith("HEIGHT="):
                h = int(line.split("=", 1)[1])
        return w, h
    except Exception:
        return 0, 0


def find_wechat_window(quiet=False, timeout=0):
    """找微信主窗口。同名窗口可能有多个(登录窗/主窗), 取面积最大的那个。"""
    if not _which("xdotool"):
        return None
    deadline = time.time() + max(0, timeout)
    while True:
        best, best_area = None, 0
        for name in WINDOW_NAMES:
            try:
                out = sh(["xdotool", "search", "--onlyvisible", "--name", name],
                         check=False, timeout=10)
            except Exception:
                return None
            for line in out.split():
                if not line.strip().isdigit():
                    continue
                wid = int(line.strip())
                w, h = _window_size(wid)
                if w * h > best_area:
                    best, best_area = wid, w * h
        if best or time.time() >= deadline:
            if not best and not quiet:
                log("未找到微信窗口, 候选窗口列表:\n" + (sh(["wmctrl", "-l"], check=False) or "(空)"))
            return best
        time.sleep(2)


# ---------------- 微信发送器 (X11 自动化) ----------------

class X11WeChatSender:
    """用 xdotool + xclip 操作微信 Linux 客户端。纯模拟键鼠, 不做内存注入/改包。"""

    def __init__(self, verify=True, search_click=None, maximize=True, dry_run=False):
        if not _which("xdotool") or not _which("xclip"):
            sys.exit("缺少依赖: xdotool / xclip 未安装(容器镜像里应已自带)")
        if not _display_ok():
            sys.exit(f"无法连接 X 服务(DISPLAY={DISPLAY}), 请确认容器内 Xvfb 已启动")
        self.verify = verify
        self.search_click = search_click      # "x,y" 时改用点击搜索框
        self.maximize = maximize
        self.dry_run = dry_run
        self._ocr_ok = bool(_which("tesseract")) and bool(_which("import", "magick"))
        self._wid = None
        self._refresh_window()
        log(f"微信客户端已就绪 ✔ (window id={self._wid})")
        if verify and not self._ocr_ok:
            log("提示: 未安装 tesseract/ImageMagick, 群名校验降级为「跳过」，仅靠搜索精确匹配")

    # ---- 基础动作 ----

    def _refresh_window(self):
        wid = find_wechat_window(timeout=60)
        if not wid:
            sys.exit("未找到微信窗口。请先在浏览器打开 noVNC, 启动并扫码登录微信后再启动中继。")
        self._wid = wid
        if self.maximize:
            try:
                sh(["xdotool", "windowactivate", "--sync", str(wid)], check=False)
                sh(["xdotool", "windowsize", str(wid), "100%", "100%"], check=False)
                sh(["xdotool", "windowmove", str(wid), "0", "0"], check=False)
            except Exception:
                pass

    def _activate(self):
        if not self._wid:
            self._refresh_window()
        sh(["xdotool", "windowactivate", "--sync", str(self._wid)], check=False, timeout=15)
        time.sleep(0.4)

    def _key(self, keys, delay=0.15):
        sh(["xdotool", "key", "--clearmodifiers", keys], check=False, timeout=15)
        time.sleep(delay)

    def _set_clipboard(self, text):
        r = subprocess.run(["xclip", "-selection", "clipboard", "-i"],
                           input=text.encode("utf-8"), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=_env(), timeout=15)
        if r.returncode != 0:
            raise RuntimeError("写入剪贴板失败: " + r.stderr.decode("utf-8", "ignore")[:200])

    def _open_search(self):
        """打开微信搜索。默认 Ctrl+F(与 Windows 版一致), 可用 --search-click 换成坐标点击。"""
        if self.search_click:
            x, y = [int(v) for v in str(self.search_click).split(",")]
            sh(["xdotool", "mousemove", str(x), str(y), "click", "1"], check=False, timeout=15)
        else:
            self._key("ctrl+f", delay=0.8)

    def _screenshot(self, path):
        """整窗截图。失败返回 False(校验降级), 不影响发送。"""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if _which("import"):
                sh(["import", "-window", str(self._wid), path], check=False, timeout=30)
            elif _which("magick", "convert"):
                sh([_which("magick", "convert"), "-window", str(self._wid), path],
                   check=False, timeout=30)
            return os.path.exists(path)
        except Exception as e:
            log(f"⚠ 截图失败({type(e).__name__}), 跳过群名校验: {e}")
            return False

    def _capture_header_text(self):
        """截取会话头部(群名那一行)并 OCR。返回识别文本; 无法校验时返回 None。"""
        conv = _which("magick", "convert")
        tsv = _which("tesseract")
        if not (conv and tsv):
            return None
        try:
            shot = VERIFY_SHOT
            if not self._screenshot(shot):
                return None
            w, h = _window_size(self._wid)
            if w <= 0 or h <= 0:
                return None
            # 会话头部: 右栏顶部那条(群名 + 成员数)
            cx, cy = int(w * 0.30), 0
            cw, ch = int(w * 0.70), max(40, int(h * 0.12))
            crop = shot + ".header.png"
            sh([conv, shot, "-crop", f"{cw}x{ch}+{cx}+{cy}", "+repage", crop],
               check=False, timeout=30)
            if not os.path.exists(crop):
                return None
            out = sh([tsv, crop, "stdout", "-l", "chi_sim+eng", "--psm", "6"],
                     check=False, timeout=60)
            try:
                os.remove(crop)
            except OSError:
                pass
            return " ".join(out.split())
        except Exception as e:
            log(f"⚠ OCR 校验异常({type(e).__name__}), 跳过群名校验: {e}")
            return None

    @staticmethod
    def _hit(text, target):
        """宽松匹配: 目标群名的字大部分出现在 OCR 文本里就算命中。"""
        if not text:
            return None                      # 无法判定
        norm = lambda s: "".join(ch for ch in s if ch.isalnum())
        t, s = norm(target), norm(text)
        if not t:
            return False
        if t in s:
            return True
        hit = sum(1 for ch in set(t) if ch in s)
        return (hit / len(set(t))) >= VERIFY_HIT_RATIO

    # ---- 主流程 ----

    def send(self, target, content):
        content = (content or "").rstrip("\n")
        if not content:
            raise RuntimeError("消息内容为空")
        target = (target or "").strip()
        if not target:
            raise RuntimeError("未配置接收群名称")

        self._activate()
        self._refresh_window_soft()

        # 1) 搜索并打开目标会话
        self._open_search()
        time.sleep(0.5)
        self._key("ctrl+a", delay=0.1)
        self._key("BackSpace", delay=0.2)
        self._set_clipboard(target)
        self._key("ctrl+v", delay=0.9)
        self._key("Return", delay=1.4)       # 打开搜索结果第一条

        # 2) 校验当前会话确实是目标群 —— 不通过就直接失败, 绝不把内容发出去
        if self.verify:
            txt = self._capture_header_text()
            res = self._hit(txt or "", target)
            if res is False:
                raise RuntimeError(
                    f"群名校验失败: 当前会话不是「{target}」(识别到「{(txt or '')[:40]}」), 已中止发送")
            if res is None:
                log(f"⚠ 未能校验会话名(OCR 不可用或未识别), 继续发送到「{target}」")
        else:
            log("⚠ 已关闭群名校验(--no-verify), 发送风险自负")

        # 3) 粘贴正文并回车
        self._set_clipboard(content)
        time.sleep(0.3)
        self._key("ctrl+v", delay=1.0)
        self._key("Return", delay=0.8)

    def _refresh_window_soft(self):
        """窗口被关掉/重建时自动重新定位(不打断发送)。"""
        w, h = _window_size(self._wid)
        if w * h < 10000:
            self._refresh_window()


# ---------------- 校准 / 自检 ----------------

def calibrate():
    ok, lines = check_env()
    print("\n".join(lines))
    wid = find_wechat_window(quiet=True)
    if wid:
        w, h = _window_size(wid)
        print(f"\n微信窗口 geometry: {w}x{h}")
        print("虚拟屏幕分辨率: " + sh(["xdotool", "getdisplaygeometry"], check=False).strip())
        out = sh(["wmctrl", "-l"], check=False)
        print("当前窗口列表:\n" + (out or "(空)"))
        shot = "/data/calibrate.png"
        try:
            subprocess.run(["import", "-window", str(wid), shot], check=True, env=_env(), timeout=30)
            print(f"已截图: {shot}  (在 noVNC 或宿主机打开看坐标)")
        except Exception as e:
            print(f"截图失败: {e}")
    return ok


# ---------------- 服务器交互 ----------------

class AuthError(RuntimeError):
    """令牌无效(HTTP 401)。"""


def api_get(server, token, path, params=None):
    r = requests.get(server.rstrip("/") + path, params=params or {},
                     headers={"X-Admin-Token": token}, timeout=20)
    if r.status_code == 401:
        raise AuthError("访问令牌无效(ADMIN_TOKEN), 请检查环境变量或 --token")
    r.raise_for_status()
    return r.json()


def api_post(server, token, path, body):
    r = requests.post(server.rstrip("/") + path, json=body,
                      headers={"X-Admin-Token": token}, timeout=30)
    if r.status_code == 401:
        raise AuthError("访问令牌无效(ADMIN_TOKEN), 请检查环境变量或 --token")
    r.raise_for_status()
    return r.json()


def run_once(server, token, sender, limit=5, dry_run=False):
    j = api_get(server, token, "/api/outbox", {"status": "pending", "page_size": limit})
    if not j.get("ok"):
        log(f"取件失败: {j.get('error')}")
        return 0
    items = (j.get("data") or {}).get("items") or []
    if not items:
        return 0
    log(f"取到 {len(items)} 条待发消息")
    for it in items:
        target = (it.get("target") or "").strip()
        content = it.get("content") or ""
        idx = it.get("id")
        head = (content.splitlines() or [""])[0][:24]
        if dry_run:
            log(f"[dry-run] #{idx} → 群「{target}」: {head}…")
            continue
        try:
            sender.send(target, content)
            api_post(server, token, "/api/outbox/ack", {"ids": [idx], "ok": True})
            log(f"✔ #{idx} 已发送 → 群「{target}」: {head}…")
        except Exception as e:
            api_post(server, token, "/api/outbox/ack",
                     {"ids": [idx], "ok": False, "err": f"{type(e).__name__}: {e}"})
            log(f"✘ #{idx} 发送失败 → 群「{target}」: {e}")
        time.sleep(3.0)      # 控制频率, 降低被风控的概率
    return len(items)


def main():
    ap = argparse.ArgumentParser(description="普通微信号中继(Linux容器版): 待发队列 → 微信群")
    ap.add_argument("--server", default=DEFAULT_SERVER, help="服务地址")
    ap.add_argument("--token", default=DEFAULT_TOKEN, help="ADMIN_TOKEN 访问令牌")
    ap.add_argument("--interval", type=int, default=60, help="轮询间隔秒数(默认60)")
    ap.add_argument("--limit", type=int, default=3, help="每轮最多发几条(默认3, 建议小批量)")
    ap.add_argument("--once", action="store_true", help="只跑一轮就退出")
    ap.add_argument("--dry-run", action="store_true", help="只打印不真正发送, 也不回报")
    ap.add_argument("--check", action="store_true", help="只检查环境与令牌")
    ap.add_argument("--calibrate", action="store_true", help="打印窗口/屏幕信息并截图")
    ap.add_argument("--no-verify", action="store_true", help="关闭发送前的群名OCR校验(不推荐)")
    ap.add_argument("--search-click", default=os.environ.get("WX_SEARCH_CLICK", ""),
                    help="改用坐标点击搜索框, 形如 90,55 (Ctrl+F 无效时使用)")
    args = ap.parse_args()

    if args.calibrate:
        sys.exit(0 if calibrate() else 1)

    if not args.token:
        sys.exit("请用 --token 传入 ADMIN_TOKEN, 或设置环境变量 ADMIN_TOKEN")

    if args.check:
        ok, lines = check_env()
        print("\n".join(lines))
        try:
            health = api_get(args.server, args.token, "/api/outbox", {"page_size": 1})
            print(f"{'✔' if health.get('ok') else '✘'} 服务端连通 {args.server} — {health.get('error') or 'OK'}")
            ok = ok and bool(health.get("ok"))
        except AuthError as e:
            print(f"✘ 服务端连通 {args.server} — {e}")
            ok = False
        except Exception as e:
            print(f"✘ 服务端连通 {args.server} — {type(e).__name__}: {e}")
            ok = False
        print("\n结论: " + ("环境就绪, 可以启动中继 ✔" if ok else "存在问题, 请按上面 ✘ 项排查 ✘"))
        sys.exit(0 if ok else 1)

    sender = X11WeChatSender(verify=not args.no_verify,
                            search_click=args.search_click or None,
                            dry_run=args.dry_run)
    if args.once:
        try:
            run_once(args.server, args.token, sender, args.limit, args.dry_run)
        except AuthError as e:
            sys.exit(str(e))
        return

    log(f"开始轮询: 每 {args.interval}s 取一次, 每轮最多 {args.limit} 条"
        + ("  (dry-run)" if args.dry_run else ""))
    while True:
        try:
            n = run_once(args.server, args.token, sender, args.limit, args.dry_run)
            if n == 0:
                log("队列为空, 等待下一轮…")
        except KeyboardInterrupt:
            log("已停止")
            return
        except AuthError as e:
            sys.exit(str(e))
        except Exception as e:
            log(f"本轮异常(不影响后续): {type(e).__name__}: {e}")
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    main()

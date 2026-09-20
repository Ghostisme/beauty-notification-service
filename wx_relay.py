# -*- coding: utf-8 -*-
"""
普通微信号中继 (Windows 端) —— 零备案/零认证把消息发到微信群

为什么需要它:
  个人微信号腾讯没有开放任何服务端接口, 所以"用普通微信号发群"只能在
  你自己的 Windows 电脑上, 通过自动化操作「微信 PC 客户端」来完成。
  好处: 完全绕开企业微信的 企业认证 / 可信域名 / 可信IP / ICP备案 全部要求。
  代价: 属于客户端自动化操作, 违反《微信个人帐号使用规范》有账号风险,
        请务必使用小号、控制频率、不要发营销骚扰内容。

工作原理:
  服务器端把要发的文案写进「待发队列」(outbox 表), 本脚本定时轮询:
      GET  /api/outbox?status=pending   → 取件
      用微信客户端把文本发到指定群
      POST /api/outbox/ack              → 回报成功/失败(失败会自动重试, 最多5次)

用法:
  微信 3.9.x:  pip install wxauto requests          (wxauto 已从 PyPI 下架, 装  pip install git+https://github.com/cluic/wxauto.git)
  微信 4.x  :  pip install wechatauto-replica requests
  脚本自动探测: 优先 wxauto, 初始化失败自动切 wechatauto-replica, 无需手动选择。
  python wx_relay.py --server https://notification.hongquanquan.cn --token 你的ADMIN_TOKEN
  python wx_relay.py --server ... --token ... --once          # 只跑一轮(调试)
  python wx_relay.py --server ... --token ... --dry-run       # 只打印不发送
  python wx_relay.py --check                                  # 只检查微信客户端是否可用
  python wx_relay.py --list-groups                            # 打印本机微信会话名(核对群名/查找客户群)

关于「群主是企微成员的群」(= 企业微信客户群):
  企业微信的客户群(群主是企微成员、成员里含微信客户), 在微信侧**就是普通微信群**,
  微信 PC 客户端不会区分内部群/客户群 —— 所以只要本机登录的这个微信号已经在该群里,
  本脚本就能直接发送。不需要企业认证/可信域名/可信IP/ICP备案, 也不经过企微任何接口。
  这也是目前**唯一能全自动**发到客户群的路径(官方「企业群发」API 必须由群主在手机端
  手动点确认, 且每个客户群每天默认只能收 1 条)。
  两个硬前提:
    1) 本机登录的微信号必须是该群成员 —— 客户群要让企微群主把这个号作为外部联系人拉进群;
    2) 群名要在企微侧设成唯一且好认的名字。门店群统一按「品牌-省-市门店店」命名,
       例如 玥笙-辽宁-大连中山店, 重名时脚本会直接报错而不是随便挑一个发,
       避免把 A 店的消息发到 B 店的客户群。
  不知道群名的准确写法? 跑 `python wx_relay.py --list-groups` 把本机微信的会话名原样
  打印出来, 复制粘贴进后台的「微信接收群名称」, 避免空格/emoji 对不上。
  首次打通链路建议先发到【测试群】(例如 抖音本地生活订单通知): 在后台
  「待发队列」页签点「🧪 发一条测试消息」, 群里收到即说明整条链路是通的。

前置条件:
  1. Windows 电脑已登录微信 PC 客户端并保持运行(可最小化, 不要锁屏休眠)
  2. 目标群已经在你的微信里(群名称要与服务器配置完全一致)
  3. 微信窗口没有被"勿扰/隐藏"
  4. 群没有被设成「不显示该聊天」(不显示的会话不在会话列表里, 脚本会报"列表里没有该群")
"""

import argparse
import os
import sys
import time

import requests

DEFAULT_SERVER = os.environ.get("RELAY_SERVER", "https://notification.hongquanquan.cn")
DEFAULT_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def log(msg):
    print(time.strftime("[%Y-%m-%d %H:%M:%S]") + " " + str(msg), flush=True)


# ---------------- 微信客户端封装 ----------------

class WeChatSender:
    """驱动微信 PC 客户端发送消息。不做内存注入, 相对温和。

    双后端自动探测:
      - wxauto            → 微信 3.9.x (UIAutomation 控件树)
      - wechatauto-replica → 微信 4.x   (微信4.1.12+ 把 UIA 树关了, 该库用 UIA热激活+OCR 兜底)
    """

    def __init__(self):
        errors = []
        # 后端1: wxauto (微信 3.9.x)
        try:
            from wxauto import WeChat
            self.wx = WeChat()
            self.backend = "wxauto"
            log("微信客户端已就绪 ✔ (后端: wxauto, 适配微信 3.9.x)")
            return
        except ImportError as e:
            errors.append(f"wxauto 未安装({e})")
        except Exception as e:
            errors.append(f"wxauto 初始化失败({e})")
        # 后端2: wechatauto-replica (微信 4.x)
        try:
            from wechatauto import WeChat
            self.wx = WeChat()
            self.backend = "wechatauto"
            log("微信客户端已就绪 ✔ (后端: wechatauto-replica, 适配微信 4.x)")
            return
        except ImportError:
            errors.append("wechatauto-replica 未安装 —— 微信4.x 需要: pip install wechatauto-replica")
        except Exception as e:
            errors.append(f"wechatauto 初始化失败({e})")
        sys.exit("未能连接微信 PC 客户端, 请先登录并保持微信运行。原因:\n  " + "\n  ".join(errors))

    # ---- 会话列表 ----

    def session_names(self):
        """读取微信会话列表里的会话名。

        为什么非要先读列表, 不直接 ChatWith:
          客户群重名很常见(多家门店的群都叫「客户服务群」), ChatWith 会命中第一条,
          消息就发到别的门店的客户群里去了 —— 这是发错群最贵的错法, 宁可报错让人来管。
        返回 list[str]; 读不到时返回 None(表示"无法校验", 不阻断发送)。
        """
        for method in ("GetSessionList", "GetSession"):
            fn = getattr(self.wx, method, None)
            if not callable(fn):
                continue
            try:
                raw = fn()
            except Exception as e:
                log(f"⚠ 读取会话列表失败({type(e).__name__}: {e}), 跳过群名预检")
                return None
            names = []
            for it in raw or []:
                if isinstance(it, str):
                    names.append(it)
                elif isinstance(it, dict):
                    for key in ("name", "Name", "nickname", "nickName", "chat_name", "昵称"):
                        if it.get(key):
                            names.append(str(it[key]))
                            break
                else:
                    # wechatauto 的 SessionItem 等对象: 先取 name 属性, 再兜底 str()
                    got = None
                    for attr in ("name", "Name", "nickname", "nickName"):
                        v = getattr(it, attr, None)
                        if isinstance(v, str) and v.strip():
                            got = v
                            break
                    names.append(got if got is not None else str(it))
            if names:
                return names
        log("⚠ 当前 wxauto 版本不支持读取会话列表, 跳过群名预检(仅按名称直接切换)")
        return None

    def resolve(self, target):
        """把配置里的群名解析成"会话列表里真实存在的那个名字"。

        精确匹配优先; 只有一个模糊命中时才采用(带警告); 命中多个直接报错。
        """
        names = self.session_names()
        if names is None:
            return target
        exact = [n for n in names if n == target]
        if len(exact) == 1:
            return target
        if len(exact) > 1:                       # 会话列表里同时存在两个完全同名的群
            raise RuntimeError(
                f"微信里有多个会话都叫「{target}」, 无法确定发给哪一个 —— "
                f"请在企微侧把群名改成唯一(例如加门店后缀)后重试")
        fuzzy = [n for n in names if target and target in n]
        if len(fuzzy) == 1:
            log(f"⚠ 未精确匹配「{target}」, 采用唯一相近的会话「{fuzzy[0]}」")
            return fuzzy[0]
        if len(fuzzy) > 1:
            raise RuntimeError(
                f"「{target}」匹配到多个会话: {fuzzy} —— 请把群名写完整后重试")
        raise RuntimeError(
            f"这台机器上的微信号会话列表里找不到「{target}」。请逐项确认: "
            f"① 群是不是被改名了 —— 用 python wx_relay.py --list-groups 看新名字, "
            f"然后到后台把商户的「微信接收群名称」改成新名字并保存"
            f"(队列里还指着旧群名的消息会自动重新绑定, 无需逐条删); "
            f"② 该群是否已存在于本机微信(客户群需让企微群主把本号拉进群); "
            f"③ 群名是否与后台配置完全一致(空格/emoji/括号); "
            f"④ 该群是否被设成了「不显示该聊天」")

    def list_sessions(self):
        """打印本机微信里的会话名, 供直接复制到后台配置。"""
        names = self.session_names()
        if not names:
            log("未读取到会话列表(微信未登录/窗口未打开/该版本不支持)")
            return False
        log(f"本机微信共有 {len(names)} 个会话, 名称如下(复制需要的那个填到后台「微信接收群名称」):")
        for i, n in enumerate(names, 1):
            print(f"  {i:>3}. {n}")
        return True

    # ---- 发送 ----

    def send(self, target, content):
        """发到指定群。先校验会话存在且唯一, 再切换并校验当前会话, 避免发错群。"""
        target = (target or "").strip()
        if not target:
            raise RuntimeError("未配置接收群名称")
        try:
            resolved = self.resolve(target)
        except RuntimeError as e:
            # 会话列表里没有, 但群可能真实存在(独立聊天窗口/列表只渲染前N条)。
            # wechatauto 的 ChatWith 走搜索框, 不依赖会话列表 —— 降级为"搜索+群类型校验"。
            if self.backend == "wechatauto" and "找不到" in str(e):
                log(f"⚠ 会话列表没有「{target}」, 改用搜索方式打开(带群类型校验)")
                self._send_via_search(target, content)
                return
            raise
        result = self.wx.ChatWith(resolved)
        time.sleep(0.5)
        # wechatauto 的 ChatWith 失败返回 None; wxauto 失败直接抛异常
        if result is None:
            raise RuntimeError(f"未找到群「{resolved}」, 请核对群名称(可用 --list-groups 对照)")
        # wechatauto: 用 ChatInfo 校验当前会话, 顺带确认是群聊(防发错人)
        info_fn = getattr(self.wx, "ChatInfo", None)
        if callable(info_fn):
            try:
                info = info_fn() or {}
                cname = str(info.get("chat_name") or "")
                if cname and str(resolved) not in cname and cname not in str(resolved):
                    raise RuntimeError(f"未找到群「{resolved}」(当前会话为「{cname}」), 请核对群名称")
            except RuntimeError:
                raise
            except Exception:
                pass
        # wxauto: 兼容旧校验路径
        current = None
        for attr in ("CurrentChat",):
            fn = getattr(self.wx, attr, None)
            if callable(fn):
                try:
                    current = fn()
                    break
                except Exception:
                    pass
        if current and str(resolved) not in str(current):
            raise RuntimeError(f"未找到群「{resolved}」(当前会话为「{current}」), 请核对群名称")
        self.wx.SendMsg(content)
        time.sleep(1.0)
        self._verify_sent(content)

    def _send_via_search(self, target, content):
        """会话列表预检失败时的降级发送: 搜索框精确打开 → 校验群类型与名字 → 发送。

        校验失败一律中止并抛错(触发回报 failed), 宁可失败不可发错群。
        """
        result = self.wx.ChatWith(target, exact=True)
        time.sleep(0.5)
        if not result:
            raise RuntimeError(
                f"搜索打开「{target}」失败 —— 该名下没有完全匹配的会话。"
                f"请核对群名(空格/emoji/括号), 并确认本微信号还在群里")
        info_fn = getattr(self.wx, "ChatInfo", None)
        if callable(info_fn):
            try:
                info = info_fn() or {}
                cname = str(info.get("chat_name") or "")
                ctype = str(info.get("chat_type") or "")
                if ctype and ctype != "group":
                    raise RuntimeError(
                        f"「{target}」命中的不是群聊(识别为 {ctype}), 为防发错人已中止发送")
                if cname and target not in cname and cname not in target:
                    raise RuntimeError(
                        f"搜索命中的会话是「{cname}」而非「{target}」, 已中止发送")
            except RuntimeError:
                raise
            except Exception:
                pass
        self.wx.SendMsg(content)
        time.sleep(1.0)
        self._verify_sent(content)

    def _verify_sent(self, content):
        """尽力回读最后一条消息, 确认内容确实落在这个会话里。

        只告警不抛异常: 回读失败不代表没发出去(版本差异/消息未渲染都会失败),
        若抛异常会触发重试, 反而可能把同一条消息重复发进客户群。
        """
        fn = getattr(self.wx, "GetLastMessage", None)
        if not callable(fn):
            return
        try:
            last = fn()
            text = ""
            if isinstance(last, dict):
                text = str(last.get("content") or last.get("msg") or "")
            elif last is not None:
                text = str(getattr(last, "content", last))
            head = (content or "").strip().splitlines()[0][:12] if (content or "").strip() else ""
            if head and text and head not in text.replace("\n", ""):
                log(f"⚠ 回读到的最后一条消息与刚发送的内容不一致, 请人工核对是否发错群: {text[:60]}")
        except Exception as e:
            log(f"⚠ 回读校验跳过({type(e).__name__}: {e})")



# ---------------- 服务器交互 ----------------

def api_get(server, token, path, params=None):
    r = requests.get(server.rstrip("/") + path, params=params or {},
                     headers={"X-Admin-Token": token}, timeout=20)
    if r.status_code == 401:
        sys.exit("访问令牌无效(ADMIN_TOKEN), 请用 --token 传入正确值")
    r.raise_for_status()
    return r.json()


def api_post(server, token, path, body):
    r = requests.post(server.rstrip("/") + path, json=body,
                      headers={"X-Admin-Token": token}, timeout=30)
    if r.status_code == 401:
        sys.exit("访问令牌无效(ADMIN_TOKEN), 请用 --token 传入正确值")
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
        target, content, idx = it.get("target") or "", it.get("content") or "", it.get("id")
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
        time.sleep(2.0)   # 控制频率, 降低风控概率
    return len(items)


def main():
    ap = argparse.ArgumentParser(description="普通微信号中继: 把服务器待发队列的消息发到微信群")
    ap.add_argument("--server", default=DEFAULT_SERVER, help="服务地址, 如 https://notification.hongquanquan.cn")
    ap.add_argument("--token", default=DEFAULT_TOKEN, help="ADMIN_TOKEN 访问令牌")
    ap.add_argument("--interval", type=int, default=60, help="轮询间隔秒数(默认60)")
    ap.add_argument("--limit", type=int, default=5, help="每轮最多发几条(默认5, 建议小批量)")
    ap.add_argument("--once", action="store_true", help="只跑一轮就退出")
    ap.add_argument("--dry-run", action="store_true", help="只打印不真正发送, 也不回报")
    ap.add_argument("--check", action="store_true", help="只检查微信客户端与令牌是否可用")
    ap.add_argument("--list-groups", action="store_true",
                    help="只打印本机微信的会话名(用来准确复制群名到后台, 不需要令牌)")
    args = ap.parse_args()

    if args.list_groups:
        sys.exit(0 if WeChatSender().list_sessions() else 1)

    if not args.token:
        sys.exit("请用 --token 传入 ADMIN_TOKEN, 或设置环境变量 ADMIN_TOKEN")

    health = api_get(args.server, args.token, "/api/outbox", {"page_size": 1})
    if not health.get("ok"):
        sys.exit(f"服务器连通性异常: {health.get('error')}")
    log(f"服务器连通 ✔ {args.server}")

    sender = WeChatSender() if not args.check else None
    if args.check:
        log("检查完成(--check), 未启动轮询。")
        return

    log(f"开始轮询: 每 {args.interval}s 取一次, 每轮最多 {args.limit} 条"
        + (" (dry-run)" if args.dry_run else ""))
    while True:
        try:
            n = run_once(args.server, args.token, sender, args.limit, args.dry_run)
            if n == 0:
                log("队列为空, 等待下一轮…")
        except KeyboardInterrupt:
            log("已停止")
            return
        except Exception as e:
            log(f"本轮异常(不影响后续): {type(e).__name__}: {e}")
        if args.once:
            return
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()

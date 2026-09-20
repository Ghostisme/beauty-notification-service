# -*- coding: utf-8 -*-
"""
wx_relay.py(Windows 中继) 回归测试 —— 不需要真实微信客户端 / 不需要 wxauto。

做法: 往 sys.modules 里塞一个假的 wxauto 模块, 用它模拟微信客户端的
      会话列表 / 切换会话 / 发送, 从而在任意平台上验证发送前的群名解析逻辑。

覆盖(重点都是"发错群"这一类不可逆错误):
  1) 群名精确命中且唯一 → 正常发送到该群
  2) 会话列表里没有该群 → 直接报错, 且**绝不切换会话、绝不发送**
  3) 两个完全同名的群 → 报错(宁可失败也不能随便挑一个)
  4) 只有一个模糊命中 → 采用并告警
  5) 多个模糊命中 → 报错
  6) 切换后当前会话不是目标群 → 正文不发送
  7) --list-groups 能打印会话名

运行: python tests/test_relay_win.py
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SESSIONS = {"v": []}          # 模拟微信会话列表
CURRENT = {"v": ""}           # 模拟 ChatWith 之后的当前会话
SENT = []                     # 记录发出的消息
CHATS = []                    # 记录 ChatWith 的调用


class FakeWeChat:
    def __init__(self, *a, **kw):
        pass

    def GetSessionList(self, reset=False):
        return list(SESSIONS["v"])

    def ChatWith(self, who, **kw):
        CHATS.append(who)
        # 只有会话列表里存在才会真的切过去, 否则保持原会话(模拟真实客户端)
        CURRENT["v"] = who if who in SESSIONS["v"] else ""

    def CurrentChat(self):
        return CURRENT["v"]

    def SendMsg(self, msg, who=None, **kw):
        if who:
            self.ChatWith(who)
        SENT.append(msg)

    def GetLastMessage(self):
        return {"content": SENT[-1] if SENT else ""}


# 注入假 wxauto, 必须在 import wx_relay 之前
sys.modules.setdefault("wxauto", types.ModuleType("wxauto"))
sys.modules["wxauto"].WeChat = FakeWeChat

import wx_relay as R          # noqa: E402


def reset(sessions, current=""):
    SESSIONS["v"] = list(sessions)
    CURRENT["v"] = current
    SENT.clear()
    CHATS.clear()


def sender():
    s = R.WeChatSender.__new__(R.WeChatSender)   # 跳过 __init__(不碰真实微信)
    s.wx = FakeWeChat()
    return s


def expect_raises(fn, *needles):
    try:
        fn()
    except Exception as e:
        msg = str(e)
        for n in needles:
            assert n in msg, f"错误信息里应包含「{n}」, 实际: {msg}"
        return msg
    raise AssertionError("预期抛异常, 但执行成功了")


def main():
    s = sender()

    # 1) 精确命中且唯一 → 正常发送
    reset(["客户服务群(超英)", "客户服务群(尹欣)", "余乐圈内部群"])
    s.send("客户服务群(超英)", "第一条")
    assert SENT == ["第一条"], SENT
    assert CHATS == ["客户服务群(超英)"], CHATS
    print("✔ 1 精确命中唯一群 → 正常发送")

    # 2) 会话列表里没有该群 → 报错且绝不发送(核心安全红线)
    reset(["客户服务群(尹欣)"])
    expect_raises(lambda: s.send("不存在的群", "别发出去"), "找不到", "客户群", "--list-groups")
    assert SENT == [], f"未命中群时不该发出任何消息, 实际: {SENT}"
    assert CHATS == [], f"未命中群时不该切换会话, 实际: {CHATS}"
    print("✔ 2 群不存在 → 报错且零发送、零切换")

    # 3) 两个完全同名的群 → 报错
    reset(["美业客户群", "美业客户群"])
    expect_raises(lambda: s.send("美业客户群", "x"), "多个会话都叫")
    assert SENT == [], f"重名时不该发送, 实际: {SENT}"
    print("✔ 3 完全重名(两个会话同名) → 报错且零发送")

    # 4) 只有一个模糊命中 → 采用并告警
    reset(["门店A客户服务群"], current="门店A客户服务群")
    s.send("客户服务群", "第二条")
    assert SENT == ["第二条"] and CHATS == ["门店A客户服务群"], (SENT, CHATS)
    print("✔ 4 唯一模糊命中 → 采用该会话发送")

    # 5) 多个模糊命中 → 报错
    reset(["门店A客户服务群", "门店B客户服务群"])
    expect_raises(lambda: s.send("客户服务群", "x"), "匹配到多个会话")
    assert SENT == [], f"模糊多命中时不该发送, 实际: {SENT}"
    print("✔ 5 模糊多命中 → 报错且零发送")

    # 6) 切换后当前会话不是目标群 → 正文不发送
    reset(["客户服务群(超英)", "别的群"])
    s.wx.ChatWith = lambda who, **kw: None       # 假装切换"失败", 当前会话留在别的群
    CURRENT["v"] = "别的群"
    expect_raises(lambda: s.send("客户服务群", "x"), "未找到群")
    assert SENT == [], f"会话不匹配时不该发送正文, 实际: {SENT}"
    print("✔ 6 会话未切换成功 → 正文不发送")

    # 7) 读不到会话列表(老版本 wxauto) → 不阻断, 直接按名字切
    reset([])
    old = s.wx.GetSessionList
    s.wx.GetSessionList = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("not supported"))
    s.wx.ChatWith = lambda who, **kw: CURRENT.__setitem__("v", who)
    s.send("任意群名", "第三条")
    assert SENT == ["第三条"], SENT
    s.wx.GetSessionList = old
    print("✔ 7 会话列表不可读 → 降级为直接按名切换(不阻断)")

    # 8) --list-groups 打印
    reset(["客户服务群(超英)", "余乐圈内部群"])
    assert s.list_sessions() is True
    print("✔ 8 --list-groups 正常输出会话名")

    print("\n全部 8 项通过 ✔")


if __name__ == "__main__":
    main()

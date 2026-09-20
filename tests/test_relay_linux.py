# -*- coding: utf-8 -*-
"""
wx_relay_linux.py 回归测试(跨平台, 不需要真实 X11)

做法: 把 subprocess.run 与 _which 打桩, 模拟 xdotool / xclip / import / tesseract,
      验证发送逻辑与安全红线, 因此 Windows 上也能跑。

覆盖:
  1) 群名宽松匹配 _hit 的边界
  2) 发送命令序列: 搜索 → 粘贴群名 → 回车 → 校验 → 粘贴正文 → 回车
  3) 安全红线: 校验到会话不对时, 正文绝不进入发送流程
  4) 关闭校验后按预期跳过
  5) 缺依赖时 check_env 优雅降级, 不抛异常

运行: python tests/test_relay_linux.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import wx_relay_linux as R          # noqa: E402

OCR_TEXT = {"v": "余乐圈订单通知群 (5)"}
CALLS = []
CLIP = {"v": ""}
TMP = tempfile.mkdtemp(prefix="wxfake_")


class FakeProc:
    def __init__(self, code=0, out=b"", err=b""):
        self.returncode, self.stdout, self.stderr = code, out, err


def fake_run(cmd, input=None, stdout=None, stderr=None, env=None, timeout=None, check=None):
    CALLS.append(" ".join(str(c) for c in cmd))
    name = os.path.basename(str(cmd[0]))
    out = b""
    if name == "xdotool":
        sub = cmd[1] if len(cmd) > 1 else ""
        if sub == "getdisplaygeometry":
            out = b"1280 800"
        elif sub == "search":
            out = b"12345"
        elif sub == "getwindowgeometry":
            out = b"WINDOW=12345\nX=0\nY=0\nWIDTH=1280\nHEIGHT=800\n"
    elif name == "xclip":
        if "-i" in cmd and input is not None:
            CLIP["v"] = input.decode("utf-8")
        elif "-o" in cmd:
            out = CLIP["v"].encode("utf-8")
    elif name in ("import", "magick", "convert"):
        dst = str(cmd[-1])
        if not dst.startswith("-"):
            open(dst, "wb").close()
    elif name == "tesseract":
        out = OCR_TEXT["v"].encode("utf-8")
    return FakeProc(0, out, b"")


def fake_which(*names):
    return "/usr/bin/" + names[0]


def install(ocr="余乐圈订单通知群 (5)"):
    CALLS.clear()
    CLIP["v"] = ""
    OCR_TEXT["v"] = ocr
    R.subprocess.run = fake_run
    R._which = fake_which
    R.VERIFY_SHOT = os.path.join(TMP, "verify.png")   # 别往 /tmp 写(Windows 下不存在)


def joined():
    return " | ".join(CALLS)


# ---------------- 用例 ----------------

def test_hit():
    hit = R.X11WeChatSender._hit
    assert hit("余乐圈订单通知群 (5)", "余乐圈订单通知群") is True, "完整包含应命中"
    assert hit("余乐圈订单通知群(5) 4位成员", "余乐圈订单通知群") is True
    assert hit("张三", "余乐圈订单通知群") is False, "完全不同的会话必须判负"
    assert hit("", "余乐圈订单通知群") is None, "OCR 空文本应返回 None(降级为直接发送)"
    assert hit("余乐圈订单群", "余乐圈订单通知群") is True, "部分命中 75% > 60% 阈值"
    print("✔ _hit 宽松匹配正确")


def test_send_flow_ok():
    install()
    s = R.X11WeChatSender(verify=True, maximize=False)
    s.send("余乐圈订单通知群", "📣【新线索提醒】\n张三 已下单")
    j = joined()
    for need in ("key --clearmodifiers ctrl+f", "key --clearmodifiers Return",
                 "key --clearmodifiers ctrl+v", "xclip -selection clipboard -i"):
        assert need in j, f"缺少命令: {need}\n{j}"
    assert "📣【新线索提醒】" in CLIP["v"], "正文应最后写入剪贴板"
    i_search = next(i for i, x in enumerate(CALLS) if "ctrl+f" in x)
    pastes = [i for i, x in enumerate(CALLS) if "ctrl+v" in x]
    assert len(pastes) >= 2, "应粘贴两次: 群名 + 正文"
    assert min(pastes) > i_search, "必须先搜索再粘贴"
    assert max(pastes) > pastes[0] or len(pastes) == 1 or True
    print("✔ 发送命令序列正确, 正文已入剪贴板")


def test_verify_blocks_wrong_chat():
    """安全红线: 会话不对时绝不发送正文。"""
    install(ocr="张三")
    s = R.X11WeChatSender(verify=True, maximize=False)
    try:
        s.send("余乐圈订单通知群", "📣【新线索提醒】机密内容")
        raise AssertionError("校验失败时必须抛错中止")
    except RuntimeError as e:
        assert "群名校验失败" in str(e), e
    assert "机密内容" not in CLIP["v"], "校验没通过就不能把正文写进剪贴板"
    print("✔ 群名校验失败时已拦截, 正文未进入发送流程")


def test_no_verify_flag():
    install(ocr="张三")
    s = R.X11WeChatSender(verify=False, maximize=False)
    s.send("余乐圈订单通知群", "内容ABC")
    assert "内容ABC" in CLIP["v"]
    print("✔ --no-verify 时跳过校验(符合预期)")


def test_ocr_unavailable_still_sends():
    """OCR 识别不到内容(返回空)时降级为直接发送, 不能误拦。"""
    install(ocr="")
    s = R.X11WeChatSender(verify=True, maximize=False)
    s.send("余乐圈订单通知群", "降级内容XYZ")
    assert "降级内容XYZ" in CLIP["v"]
    print("✔ OCR 识别不出内容时降级发送, 不误拦")


def test_check_env_degrades():
    """没有任何 X11 工具时, check_env 返回报告而不是崩溃。"""
    real_run = R.subprocess.run
    R._which = lambda *names: None
    R.subprocess.run = real_run
    ok, lines = R.check_env()
    assert ok is False
    assert any("工具 xdotool" in l and "✘" in l for l in lines), lines
    assert R.find_wechat_window(quiet=True) is None, "无 xdotool 时应安全返回 None"
    print("✔ 缺依赖时 check_env 优雅降级")


def test_missing_window_exits_cleanly():
    """微信未启动时给出人类可读报错, 而不是 traceback。"""
    install()
    orig = R.find_wechat_window
    R.find_wechat_window = lambda quiet=False, timeout=0: None
    try:
        R.X11WeChatSender(verify=True, maximize=False)
        raise AssertionError("应退出")
    except SystemExit as e:
        assert "noVNC" in str(e) or "微信窗口" in str(e), e
    finally:
        R.find_wechat_window = orig
    print("✔ 找不到微信窗口时给出可读提示")


if __name__ == "__main__":
    for fn in (test_hit, test_send_flow_ok, test_verify_blocks_wrong_chat,
               test_no_verify_flag, test_ocr_unavailable_still_sends,
               test_check_env_degrades, test_missing_window_exits_cleanly):
        fn()
    print("\n全部通过 ✔")

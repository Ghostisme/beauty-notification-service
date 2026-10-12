"""企微 Windows 界面发送：校准区域、精确核对群名、发送后检查消息。

此模块不注入客户端、不读取客户端数据库。OCR 只在已校准的窗口区域运行。
"""
import re
import time
import unicodedata


class BeforeSendError(RuntimeError):
    """确认没有点击发送，可以在任务队列重试。"""


class UncertainSendError(RuntimeError):
    """可能已经发送，必须由操作人核实。"""


def compact(value):
    value = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", "", value).translate(str.maketrans({"—": "-", "–": "-", "￥": "¥"}))


def exact_group(actual, expected, title=False):
    actual, expected = compact(actual), compact(expected)
    if actual == expected:
        return True
    # 企微群标题可能附带成员人数；只剥离末尾独立的成员计数。
    return bool(title and re.sub(r"\(\d+\)$", "", actual) == expected)


def confirmation_anchors(body):
    lines = [v.strip() for v in body.splitlines() if v.strip()]
    if not lines:
        raise BeforeSendError("消息内容为空")
    identifiers = [v for v in lines if v.startswith(("订单编号：", "订单编号:", "留资编号：", "留资编号:"))]
    if not identifiers:
        raise BeforeSendError("Windows 发送确认需要模板保留订单编号或留资编号")
    critical = [v for v in lines if v.startswith(("状态变化：", "状态变化:", "变化时间：", "变化时间:", "留资时间：", "留资时间:", "下单时间：", "下单时间:"))]
    return [compact(v) for v in [lines[0], *critical, *identifiers]]


def has_confirmation(ocr_text, anchors):
    value = compact(ocr_text)
    # 不做 OCR 错字的模糊匹配；识别不清时保留“待人工核实”。
    return all(anchor in value for anchor in anchors)


class WindowsDesktop:
    def __init__(self, profile):
        import os
        if os.name != "nt":
            raise RuntimeError("企微桌面发送端只支持 Windows；云端服务支持 Linux")
        import ctypes
        from ctypes import wintypes
        import win32api
        import win32con
        import win32gui
        import win32process
        from PIL import ImageGrab
        self.ctypes, self.win32api, self.win32con = ctypes, win32api, win32con
        self.win32gui, self.win32process, self.grab = win32gui, win32process, ImageGrab.grab
        self.profile = profile
        self._ocr = None
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
        user = ctypes.windll.user32
        user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user.OpenInputDesktop.restype = wintypes.HANDLE
        user.SwitchDesktop.argtypes = [wintypes.HANDLE]
        user.SwitchDesktop.restype = wintypes.BOOL
        user.CloseDesktop.argtypes = [wintypes.HANDLE]

    def unlocked(self):
        user = self.ctypes.windll.user32
        handle = user.OpenInputDesktop(0, False, 0x0100)
        if not handle:
            return False
        try:
            return bool(user.SwitchDesktop(handle))
        finally:
            user.CloseDesktop(handle)

    def find_window(self):
        matches = []
        def visit(hwnd, _):
            if not self.win32gui.IsWindowVisible(hwnd):
                return
            title = self.win32gui.GetWindowText(hwnd)
            class_name = self.win32gui.GetClassName(hwnd)
            if "企业微信" not in title and "WeCom" not in title and "WeWork" not in class_name:
                return
            try:
                _, pid = self.win32process.GetWindowThreadProcessId(hwnd)
                handle = self.win32api.OpenProcess(0x0400 | 0x0010, False, pid)
                try:
                    exe = self.win32process.GetModuleFileNameEx(handle, 0).lower()
                finally:
                    handle.Close()
                if exe.endswith("wxwork.exe"):
                    rect = self.win32gui.GetWindowRect(hwnd)
                    if rect[2] - rect[0] > 600 and rect[3] - rect[1] > 400:
                        matches.append(hwnd)
            except Exception:
                return
        self.win32gui.EnumWindows(visit, None)
        if len(matches) != 1:
            raise BeforeSendError("未找到唯一的企微主窗口，请登录并展开企业微信")
        return matches[0]

    def ready(self):
        if not self.unlocked():
            return False, "Windows 桌面已锁定，请保持发送电脑会话可交互"
        try:
            hwnd = self.find_window()
            if not all(k in self.profile for k in ("search_point", "results_rect", "header_rect", "input_point", "messages_rect", "window_size")):
                return False, "请先运行发送端界面校准"
            if self.win32gui.IsIconic(hwnd):
                return False, "企微窗口已最小化，请展开窗口"
            rect = self.win32gui.GetWindowRect(hwnd)
            w, h = self.profile["window_size"]
            if abs((rect[2]-rect[0])-w) > 8 or abs((rect[3]-rect[1])-h) > 8:
                return False, "企微窗口大小与校准时不同，请恢复窗口尺寸或重新校准"
            elapsed = (self.win32api.GetTickCount()-self.win32api.GetLastInputInfo()) & 0xFFFFFFFF
            if elapsed < self.profile.get("idle_seconds", 3)*1000:
                return False, "等待桌面空闲"
            return True, "企微桌面已就绪"
        except BeforeSendError as e:
            return False, str(e)

    def _foreground(self, hwnd):
        self.win32gui.ShowWindow(hwnd, self.win32con.SW_RESTORE)
        # Windows 限制后台进程强抢焦点；不能取得前台时直接停止本次操作。
        try:
            self.win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            raise BeforeSendError("无法切换到企微窗口，请在发送电脑上选中企微") from e
        time.sleep(0.3)
        if self.win32gui.GetForegroundWindow() != hwnd:
            raise BeforeSendError("企微没有取得桌面焦点，本次未发送")

    def _point(self, hwnd, point):
        x, y, _, _ = self.win32gui.GetWindowRect(hwnd)
        return x + int(point[0]), y + int(point[1])

    def _click(self, hwnd, point):
        if self.win32gui.GetForegroundWindow() != hwnd:
            raise BeforeSendError("桌面焦点被其他窗口占用")
        self.win32api.SetCursorPos(self._point(hwnd, point))
        self.win32api.mouse_event(self.win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        self.win32api.mouse_event(self.win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        time.sleep(0.15)

    def _key(self, *codes):
        for code in codes:
            self.win32api.keybd_event(code, 0, 0, 0)
        for code in reversed(codes):
            self.win32api.keybd_event(code, 0, self.win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.12)

    def _clipboard(self, value=None):
        import win32clipboard
        for _ in range(10):
            try:
                win32clipboard.OpenClipboard()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise BeforeSendError("剪贴板被占用，本次未发送")
        try:
            if value is None:
                return win32clipboard.GetClipboardData(self.win32con.CF_UNICODETEXT) if win32clipboard.IsClipboardFormatAvailable(self.win32con.CF_UNICODETEXT) else None
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(value, self.win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()

    def _read(self, hwnd, key):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
        rect = self.profile[key]
        x, y, _, _ = self.win32gui.GetWindowRect(hwnd)
        import numpy as np
        image = self.grab(bbox=(x+rect[0],y+rect[1],x+rect[2],y+rect[3]), all_screens=True)
        # RapidOCR 接收 numpy BGR 图片；Pillow 截图为 RGB。
        result, _ = self._ocr(np.asarray(image.convert("RGB"))[:,:,::-1].copy())
        return result or []

    def _verify_header(self, hwnd, expected):
        results = self._read(hwnd, "header_rect")
        if not any(exact_group(row[1], expected, title=True) for row in results):
            raise BeforeSendError("群标题与目标群名不完全一致，本次未发送；请检查群名或校准范围")

    def send(self, job, before_submit):
        ready, detail = self.ready()
        if not ready:
            raise BeforeSendError(detail)
        anchors = confirmation_anchors(job["text"])
        hwnd = self.find_window()
        self._foreground(hwnd)
        previous_clipboard = self._clipboard()
        submitted = False
        try:
            self._click(hwnd, self.profile["search_point"])
            self._key(self.win32con.VK_CONTROL, ord("A"))
            self._clipboard(job["group_name"])
            self._key(self.win32con.VK_CONTROL, ord("V"))
            time.sleep(self.profile.get("search_wait_seconds", 2.5))
            results = self._read(hwnd, "results_rect")
            matches = [r for r in results if exact_group(r[1], job["group_name"], title=True)]
            if len(matches) != 1:
                raise BeforeSendError("搜索结果没有唯一的完整群名匹配，本次未发送")
            points = matches[0][0]
            rect = self.profile["results_rect"]
            target = (rect[0] + sum(p[0] for p in points)/len(points), rect[1] + sum(p[1] for p in points)/len(points))
            self._click(hwnd, target)
            time.sleep(1)
            self._verify_header(hwnd, job["group_name"])
            history_before = "\n".join(r[1] for r in self._read(hwnd, "messages_rect"))
            if has_confirmation(history_before, anchors):
                raise UncertainSendError("群内已出现相同编号与事件信息，为避免重复发送，请人工核实")
            self._click(hwnd, self.profile["input_point"])
            self._key(self.win32con.VK_CONTROL, ord("A"))
            self._clipboard(job["text"])
            self._key(self.win32con.VK_CONTROL, ord("V"))
            time.sleep(0.5)
            self._verify_header(hwnd, job["group_name"])
            if self.win32gui.GetForegroundWindow() != hwnd:
                raise BeforeSendError("发送前企微焦点丢失，本次未发送")
            before_submit()  # 先持久化本地发送中状态，再点击发送，保证崩溃后不盲目重发。
            submitted = True
            if self.profile.get("send_shortcut", "enter") == "ctrl-enter":
                self._key(self.win32con.VK_CONTROL, self.win32con.VK_RETURN)
            else:
                self._key(self.win32con.VK_RETURN)
            deadline = time.monotonic() + self.profile.get("confirmation_seconds", 18)
            while time.monotonic() < deadline:
                time.sleep(1.5)
                self._verify_header(hwnd, job["group_name"])
                history = "\n".join(r[1] for r in self._read(hwnd, "messages_rect"))
                if has_confirmation(history, anchors):
                    return {"status": "sent", "detail": "已核对目标群标题及群内消息编号、事件信息", "group_id": job["group_id"]}
            raise UncertainSendError("已点击发送，但未能完整识别群内消息，请人工核实")
        except UncertainSendError:
            raise
        except Exception as e:
            if submitted:
                raise UncertainSendError("发送后确认中断，请核实目标群消息") from e
            if isinstance(e, BeforeSendError):
                raise
            raise BeforeSendError(f"发送前操作未完成：{type(e).__name__}") from e
        finally:
            try:
                self._clipboard(previous_clipboard if previous_clipboard is not None else "")
            except Exception:
                pass

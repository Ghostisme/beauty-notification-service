"""macOS 企微界面驱动：系统权限、逻辑坐标、原生中文识别。

系统框架在创建驱动时才导入，Linux 后台及 Windows 测试无需安装 PyObjC。
不使用客户端注入或私有协议；不把截图、OCR 正文写入日志。
"""
import io
import math
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .desktop import BeforeSendError, DesktopSender, profile_problem


@dataclass(frozen=True)
class MacWindow:
    window_id: int
    pid: int
    rect: tuple


def vision_box(box, width, height):
    """Vision 左下原点的归一化坐标 -> 窗口裁剪区左上原点的逻辑坐标。"""
    x, y, w, h = box
    if not all(math.isfinite(v) for v in box) or w <= 0 or h <= 0:
        raise BeforeSendError("系统文字识别返回无效位置，本次未发送")
    left, top = x * width, (1 - y - h) * height
    right, bottom = (x + w) * width, (1 - y) * height
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


class NativeMac:
    def __init__(self):
        import AppKit
        import ApplicationServices
        import Foundation
        import Quartz
        import Vision
        self.appkit, self.ax, self.foundation = AppKit, ApplicationServices, Foundation
        self.q, self.vision = Quartz, Vision

    def permissions(self, prompt=False):
        q, ax = self.q, self.ax
        accessibility = bool(ax.AXIsProcessTrustedWithOptions(
            {ax.kAXTrustedCheckOptionPrompt: bool(prompt)}))
        screen = bool(q.CGPreflightScreenCaptureAccess())
        if prompt and not screen:
            q.CGRequestScreenCaptureAccess()
            screen = bool(q.CGPreflightScreenCaptureAccess())
        missing = []
        if not accessibility:
            missing.append("辅助功能")
        if not screen:
            missing.append("屏幕录制（录屏与系统录音）")
        return not missing, ("Mac 系统权限已就绪" if not missing else
                             "请在系统设置 → 隐私与安全中允许终端 / Python 的" + "、".join(missing) + "；授权后重新打开发送端")

    def unlocked(self):
        session = self.q.CGSessionCopyCurrentDictionary()
        if not session or session.get("CGSSessionScreenIsLocked", False):
            return False
        # 该键由系统会话字典提供；缺省不据此判定已登出。
        if session.get(self.q.kCGSessionOnConsoleKey) is False:
            return False
        front = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        bundle = str(front.bundleIdentifier() or "") if front else ""
        return bundle not in ("com.apple.loginwindow", "com.apple.ScreenSaver.Engine")

    def _windows(self):
        return self.q.CGWindowListCopyWindowInfo(
            self.q.kCGWindowListOptionOnScreenOnly | self.q.kCGWindowListExcludeDesktopElements,
            self.q.kCGNullWindowID) or []

    @staticmethod
    def _main_window(row):
        b = row.get("kCGWindowBounds", {})
        return row.get("kCGWindowLayer") == 0 and b.get("Width", 0) > 600 and b.get("Height", 0) > 400

    def find_window(self):
        found = []
        for row in self._windows():
            if not self._main_window(row):
                continue
            pid = int(row["kCGWindowOwnerPID"])
            app = self.appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            bundle = str(app.bundleIdentifier() or "").lower() if app else ""
            # 只接受腾讯企微应用，不以会话标题或聊天内容判断应用身份。
            if not bundle.startswith("com.tencent.") or not any(
                    name in bundle for name in ("wework", "wxwork", "wecom")):
                continue
            b = row["kCGWindowBounds"]
            x, y = b["X"], b["Y"]
            found.append(MacWindow(int(row["kCGWindowNumber"]), pid,
                                   (x, y, x + b["Width"], y + b["Height"])))
        if len(found) != 1:
            raise BeforeSendError("未找到唯一的 Mac 企微主窗口，请登录、展开窗口并关闭独立聊天窗口")
        return found[0]

    def focused(self, window):
        if not self.unlocked():
            return False
        front = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front or front.processIdentifier() != window.pid:
            return False
        # 主窗口须仍是该应用最前面的普通窗口；同应用弹出对话框也会阻止输入。
        rows = [r for r in self._windows() if r.get("kCGWindowOwnerPID") == window.pid
                and r.get("kCGWindowLayer") == 0
                and r.get("kCGWindowBounds", {}).get("Width", 0) > 100
                and r.get("kCGWindowBounds", {}).get("Height", 0) > 100]
        return bool(rows and int(rows[0]["kCGWindowNumber"]) == window.window_id)

    def foreground(self, window):
        app = self.appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(window.pid)
        if not app or not app.activateWithOptions_(self.appkit.NSApplicationActivateIgnoringOtherApps):
            raise BeforeSendError("无法切换到 Mac 企微，请手动点击企微主窗口")
        time.sleep(0.4)
        if not self.focused(window):
            raise BeforeSendError("企微未取得焦点，请关闭弹窗并选中企微主窗口")

    def idle_seconds(self):
        return self.q.CGEventSourceSecondsSinceLastEventType(
            self.q.kCGEventSourceStateCombinedSessionState,
            getattr(self.q, "kCGAnyInputEventType", 0xFFFFFFFF))

    def click(self, x, y):
        for kind in (self.q.kCGEventMouseMoved, self.q.kCGEventLeftMouseDown, self.q.kCGEventLeftMouseUp):
            event = self.q.CGEventCreateMouseEvent(None, kind, (x, y), self.q.kCGMouseButtonLeft)
            if event is None:
                raise BeforeSendError("Mac 系统未允许鼠标控制")
            self.q.CGEventPost(self.q.kCGHIDEventTap, event)
        time.sleep(0.15)

    def key(self, key, modifier=None):
        # macOS 虚拟键码：A=0、V=9、Return=36；粘贴必须使用 Command。
        flags = {None: 0, "command": self.q.kCGEventFlagMaskCommand,
                 "control": self.q.kCGEventFlagMaskControl}[modifier]
        for down in (True, False):
            event = self.q.CGEventCreateKeyboardEvent(None, key, down)
            if event is None:
                raise BeforeSendError("Mac 系统未允许键盘控制")
            self.q.CGEventSetFlags(event, flags)
            self.q.CGEventPost(self.q.kCGHIDEventTap, event)
        time.sleep(0.12)

    def clipboard(self, value=None):
        board = self.appkit.NSPasteboard.generalPasteboard()
        if value is None:
            text = board.stringForType_(self.appkit.NSPasteboardTypeString)
            return str(text) if text is not None else None
        board.clearContents()
        if not board.setString_forType_(value, self.appkit.NSPasteboardTypeString):
            raise BeforeSendError("无法写入 Mac 剪贴板")

    def capture(self, window):
        from PIL import Image
        # 系统截图工具避免依赖已被较新 macOS 弃用的 CGWindowListCreateImage。
        # -l 按窗口 ID 截图，-o 排除阴影；保留 Retina 原图供 Vision 识别。
        with tempfile.TemporaryDirectory(prefix="laike-screen-") as folder:
            path = Path(folder) / "window.png"
            try:
                done = subprocess.run(["/usr/sbin/screencapture", "-x", "-o", "-l",
                                       str(window.window_id), str(path)], capture_output=True, timeout=8)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise BeforeSendError("Mac 窗口截图未完成，请检查屏幕录制权限") from exc
            if done.returncode or not path.is_file():
                raise BeforeSendError("Mac 窗口截图失败，请允许屏幕录制并重新启动发送端")
            with Image.open(path) as image:
                return image.convert("RGB")

    def recognize(self, image, logical_size):
        import objc
        v = self.vision
        with objc.autorelease_pool():
            request = v.VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(v.VNRequestTextRecognitionLevelAccurate)
            languages, error = request.supportedRecognitionLanguagesAndReturnError_(None)
            if error or "zh-Hans" not in (languages or []):
                raise BeforeSendError("当前 macOS 缺少简体中文文字识别，请升级系统后重新检查")
            request.setRecognitionLanguages_(["zh-Hans", "en-US"])
            request.setUsesLanguageCorrection_(False)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            data = self.foundation.NSData.dataWithBytes_length_(buffer.getvalue(), len(buffer.getvalue()))
            handler = v.VNImageRequestHandler.alloc().initWithData_options_(data, {})
            success, error = handler.performRequests_error_([request], None)
            if not success or error:
                raise BeforeSendError("Mac 系统文字识别未完成，本次未发送")
            rows = []
            for item in request.results() or []:
                candidates = item.topCandidates_(1)
                if not candidates:
                    continue
                candidate, box = candidates[0], item.boundingBox()
                points = vision_box((box.origin.x, box.origin.y, box.size.width, box.size.height), *logical_size)
                rows.append([points, str(candidate.string()), float(candidate.confidence())])
            return rows


class MacDesktop(DesktopSender):
    platform_name = "macos"

    def __init__(self, profile, native=None):
        self.profile = profile
        self.native = native or NativeMac()

    def unlocked(self):
        return self.native.unlocked()

    def find_window(self):
        return self.native.find_window()

    def window_rect(self, window):
        # 重新读取窗口位置，允许窗口移动；坐标始终使用系统逻辑点。
        current = self.find_window()
        if current.window_id != window.window_id:
            raise BeforeSendError("企微主窗口已改变，请重新启动发送端")
        return current.rect

    def capture_window(self, window):
        from PIL import Image
        rect = self.window_rect(window)
        size = (round(rect[2] - rect[0]), round(rect[3] - rect[1]))
        return self.native.capture(window).resize(size, Image.Resampling.LANCZOS)

    def ready(self):
        try:
            allowed, detail = self.native.permissions()
            if not allowed:
                return False, detail
            if not self.unlocked():
                return False, "Mac 已锁屏或切换用户，请解锁并保持企微窗口可操作"
            if self.profile.get("platform") != "darwin":
                return False, "请在这台 Mac 重新校准；不能使用 Windows 的校准文件"
            problem = profile_problem(self.profile)
            if problem:
                return False, problem
            window = self.find_window()
            x1, y1, x2, y2 = window.rect
            w, h = self.profile["window_size"]
            if abs(x2 - x1 - w) > 8 or abs(y2 - y1 - h) > 8:
                return False, "Mac 企微窗口尺寸已变化，请恢复尺寸或重新校准"
            if self.profile.get("send_shortcut", "enter") not in ("enter", "cmd-enter", "ctrl-enter"):
                return False, "企微发送快捷键配置无效，请重新校准"
            if self.native.idle_seconds() < self.profile.get("idle_seconds", 3):
                return False, "等待 Mac 桌面空闲"
            return True, "Mac 企微桌面已就绪"
        except BeforeSendError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, "Mac 系统检查未完成：" + type(exc).__name__

    def _foreground(self, window):
        self.native.foreground(window)

    def _focused(self, window):
        return self.native.focused(window)

    def _guard(self, window):
        if not self._focused(window):
            raise BeforeSendError("Mac 企微焦点丢失，请停止其他桌面操作")
        rect = self.window_rect(window)
        w, h = self.profile["window_size"]
        if abs(rect[2] - rect[0] - w) > 8 or abs(rect[3] - rect[1] - h) > 8:
            raise BeforeSendError("操作期间企微窗口尺寸改变，请重新校准")
        return rect

    def _click(self, window, point):
        rect = self._guard(window)
        self.native.click(rect[0] + point[0], rect[1] + point[1])

    def _select_all(self, window):
        self._guard(window)
        self.native.key(0, "command")

    def _paste(self, window):
        self._guard(window)
        self.native.key(9, "command")

    def _submit(self, window):
        self._guard(window)
        shortcut = self.profile.get("send_shortcut", "enter")
        self.native.key(36, {"enter": None, "cmd-enter": "command", "ctrl-enter": "control"}[shortcut])

    def _clipboard(self, value=None):
        return self.native.clipboard(value)

    def _read(self, window, key):
        rect = self._guard(window)
        image = self.native.capture(window)
        scale_x = image.width / (rect[2] - rect[0])
        scale_y = image.height / (rect[3] - rect[1])
        x1, y1, x2, y2 = self.profile[key]
        crop = image.crop((round(x1 * scale_x), round(y1 * scale_y), round(x2 * scale_x), round(y2 * scale_y)))
        # Retina 2x、外接屏 1x 均换算回校准的逻辑点，避免搜索结果点击偏移。
        return self.native.recognize(crop, (x2 - x1, y2 - y1))

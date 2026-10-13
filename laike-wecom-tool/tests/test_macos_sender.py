"""跨平台发送约定测试，不代替 Mac 实机权限、企微版本及真实发群验收。"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from sender.desktop import BeforeSendError, UncertainSendError, create_desktop
from sender.identity import sender_identity
from sender.macos import MacDesktop, MacWindow, NativeMac, vision_box
from sender.worker import Worker


GROUP = "壹心-湖南-测试消息店"
TEXT = "【抖音来客｜新订单通知】\n下单时间：2026-10-13 12:00:00\n订单编号：MAC-CHECK-01"


@pytest.fixture
def profile():
    return {"platform":"darwin", "window_size":[1000,700], "search_point":[160,38],
            "results_rect":[60,60,310,500], "header_rect":[310,0,1000,80],
            "messages_rect":[310,80,1000,500], "input_point":[500,600]}


@pytest.fixture
def job():
    return {"id":1,"group_id":"test-group","group_name":GROUP,"text":TEXT,
            "idempotency_key":"mac-check-r0","lease_token":"lease"}


class NativeFixture:
    def __init__(self):
        self.allowed = True
        self.locked = False
        self.has_focus = True
        self.window = MacWindow(123, 456, (-1000, 50, 0, 750))
        self.keys = []
        self.clicks = []
        self.capture_sizes = []
        self.result_name = GROUP
        self.header_name = GROUP
        self.duplicate = False
        self.confirm = True
        self.submitted = False
        self.clip = "原剪贴板"
        self.idle = 10

    def permissions(self, prompt=False):
        return self.allowed, "权限就绪" if self.allowed else "缺少屏幕录制"

    def unlocked(self):return not self.locked
    def find_window(self):return self.window
    def focused(self, window):return self.has_focus
    def foreground(self, window):pass
    def idle_seconds(self):return self.idle
    def click(self, x, y):self.clicks.append((x,y))
    def key(self, key, modifier=None):
        self.keys.append((key,modifier))
        if key == 36:self.submitted = True

    def clipboard(self, value=None):
        if value is None:return self.clip
        self.clip = value

    def capture(self, window):return Image.new("RGB",(2000,1400))
    def recognize(self, image, logical_size):
        self.capture_sizes.append((image.size,logical_size))
        if logical_size == (250,440):
            return [[vision_box((.1,.6,.8,.1),*logical_size),self.result_name,1]]
        if logical_size == (690,80):
            return [[[],self.header_name + " (10)",1]]
        text = TEXT if self.duplicate or (self.submitted and self.confirm) else "历史消息"
        return [[[],text,1]]


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr("sender.desktop.time.sleep",lambda seconds:None)
    ticks = iter(range(0,10000,3))
    monkeypatch.setattr("sender.desktop.time.monotonic",lambda:next(ticks))


def test_retina_ocr_boxes_click_in_logical_points_on_negative_origin_monitor(profile,job):
    native = NativeFixture()
    driver = MacDesktop(profile,native)
    submitted=[]
    assert driver.capture_window(native.window).size == (1000,700)
    assert driver.send(job,lambda:submitted.append(True))["status"] == "sent"
    assert submitted == [True]
    # 搜索结果的中心逻辑点 (185,214)，不能使用 Retina 的双倍像素。
    assert native.clicks[1] == pytest.approx((-815,264))
    assert ((500,880),(250,440)) in native.capture_sizes
    assert native.keys[:2] == [(0,"command"),(9,"command")]
    assert native.clip == "原剪贴板"


@pytest.mark.parametrize("change,reason",[("permission","屏幕录制"),("lock","锁屏"),
                                          ("platform","重新校准"),("size","尺寸"),("idle","空闲")])
def test_not_ready_stops_before_clipboard_or_keyboard(profile,job,change,reason):
    native=NativeFixture()
    if change=="permission":native.allowed=False
    if change=="lock":native.locked=True
    if change=="platform":profile["platform"]="win32"
    if change=="size":profile["window_size"]=[1100,700]
    if change=="idle":native.idle=1
    driver=MacDesktop(profile,native)
    submitted=[]
    with pytest.raises(BeforeSendError,match=reason):driver.send(job,lambda:submitted.append(True))
    assert not submitted and not native.keys and native.clip=="原剪贴板"


@pytest.mark.parametrize("wrong",["search","header","focus"])
def test_wrong_chat_or_lost_focus_never_submits(profile,job,wrong):
    native=NativeFixture()
    if wrong=="search":native.result_name=GROUP+"分店"
    if wrong=="header":native.header_name="其他门店群"
    if wrong=="focus":native.has_focus=False
    submitted=[]
    with pytest.raises(BeforeSendError):MacDesktop(profile,native).send(job,lambda:submitted.append(True))
    assert not submitted and not native.submitted


def test_duplicate_visible_event_is_left_for_manual_review(profile,job):
    native=NativeFixture();native.duplicate=True
    submitted=[]
    with pytest.raises(UncertainSendError,match="相同编号"):
        MacDesktop(profile,native).send(job,lambda:submitted.append(True))
    assert not submitted and not native.submitted


def test_after_submission_missing_confirmation_stays_uncertain_in_ledger(profile,job,tmp_path):
    native=NativeFixture();native.confirm=False
    driver=MacDesktop(profile,native)
    worker=Worker({"server":"http://localhost:1","token":"fixture","data_dir":str(tmp_path)},driver)
    receipts=[]
    worker.request=lambda path,body:receipts.append(body) or {"ok":True}
    assert worker.process(job)["status"]=="uncertain"
    assert worker.process(job)["status"]=="uncertain"
    assert native.keys.count((36,None)) == 1
    assert receipts[0]["remote_id"]=="macos-ledger:mac-check-r0"


@pytest.mark.parametrize("shortcut,modifier",[("enter",None),("cmd-enter","command"),("ctrl-enter","control")])
def test_macos_submission_respects_actual_wecom_shortcut(profile,job,shortcut,modifier):
    native=NativeFixture();profile["send_shortcut"]=shortcut
    assert MacDesktop(profile,native).send(job,lambda:None)["status"]=="sent"
    assert native.keys[-1]==(36,modifier)


def test_native_keyboard_sets_command_flags_for_paste(monkeypatch):
    events=[]
    q=SimpleNamespace(kCGEventFlagMaskCommand=16,kCGEventFlagMaskControl=32,kCGHIDEventTap=1)
    q.CGEventCreateKeyboardEvent=lambda source,key,down:{"key":key,"down":down}
    q.CGEventSetFlags=lambda event,flags:event.update(flags=flags)
    q.CGEventPost=lambda tap,event:events.append(event)
    native=NativeMac.__new__(NativeMac);native.q=q
    native.key(9,"command")
    assert events==[{"key":9,"down":True,"flags":16},{"key":9,"down":False,"flags":16}]


def test_vision_bottom_origin_conversion_and_invalid_location():
    for actual, expected in zip(vision_box((.1,.2,.4,.3),1000,700),[[100,350],[500,350],[500,560],[100,560]]):
        assert actual==pytest.approx(expected)
    with pytest.raises(BeforeSendError):vision_box((float("nan"),0,.5,.5),1000,700)


def test_factory_loads_only_selected_os_driver(monkeypatch):
    monkeypatch.setattr("sender.macos.NativeMac",lambda:NativeFixture())
    assert isinstance(create_desktop({},"darwin"),MacDesktop)
    with pytest.raises(RuntimeError,match="Linux"):create_desktop({},"linux")


def test_worker_identity_distinguishes_platform_and_computer():
    assert sender_identity("darwin","Mac-A")==sender_identity("darwin","Mac-A")
    assert sender_identity("darwin","Mac-A")[0]!=sender_identity("darwin","Mac-B")[0]
    assert sender_identity("darwin","Mac-A")[0]!=sender_identity("win32","Mac-A")[0]


def cli_module():
    spec=importlib.util.spec_from_file_location("sender_cli",Path(__file__).parents[1]/"sender.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_choose_registered_group_scope_keeps_credentials_and_excludes_other_groups(tmp_path,monkeypatch):
    cli=cli_module();path=tmp_path/"sender-config.json"
    config={"server":"http://localhost:1","token":"fixture-secret","worker_id":"existing-id",
            "group_ids":["old"],"group_names":[GROUP]}
    response=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{"items":[
        {"group_id":"g1","group_name":GROUP},{"group_id":"g2","group_name":"玥笙-辽宁-大连中山店"}]})
    monkeypatch.setattr("requests.get",lambda *a,**kw:response)
    monkeypatch.setattr("builtins.input",lambda prompt:"2")
    cli.configure_groups(path,config)
    saved=json.loads(path.read_text(encoding="utf-8"))
    assert saved["token"]=="fixture-secret" and saved["worker_id"]=="existing-id"
    assert saved["group_names"]==["玥笙-辽宁-大连中山店"] and "group_ids" not in saved


def test_invalid_group_selection_preserves_previous_file(tmp_path,monkeypatch):
    cli=cli_module();path=tmp_path/"sender-config.json";path.write_text("original",encoding="utf-8")
    response=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{"items":[{"group_name":GROUP}]})
    monkeypatch.setattr("requests.get",lambda *a,**kw:response)
    monkeypatch.setattr("builtins.input",lambda prompt:"1,999")
    with pytest.raises(ValueError):cli.configure_groups(path,{"server":"http://localhost:1","token":"fixture"})
    assert path.read_text(encoding="utf-8")=="original"

# -*- coding: utf-8 -*-
"""群改名后的「重新绑定」回归测试。

覆盖: 队列里的旧群名改指新群名 / 失败消息重置 / 幂等键重算 / 重复合并 /
     商户改名 / 不该动的商户绝不动。

运行: python tests/test_group_rebind.py   (使用临时库, 不影响 data/admin.db)
"""
import gc
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage

tmp = os.path.join(tempfile.gettempdir(), "rebind_test.db")
if os.path.exists(tmp):
    os.remove(tmp)
storage.DB_PATH = tmp
storage.init()

import web_admin  # noqa: E402  (storage.DB_PATH 已改, 不会碰真实库)

OLD, NEW = "超英客户服务群", "超英客户服务群(2026)"


def enq(content, target, merchant="超英"):
    return storage.enqueue_outbox([content], merchant=merchant,
                                  account_id="acc-1", channel="wechat_group", target=target)


def rows():
    return {it["id"]: it for it in storage.list_outbox(page_size=200)["items"]}


# ---------- 造数据 ----------
enq("msg-1", OLD)                     # 待发
enq("msg-2", OLD)                     # 待发 -> 打成 failed
enq("msg-3", "别的群")                 # 同商户但不同群名(不该被 old_target 命中)
enq("msg-4", NEW)                     # 已经指向新群
enq("msg-5", OLD, merchant="尹欣")     # 别的商户, 绝不该被动

ids = sorted(rows())
failed_id = ids[1]
for _ in range(storage.MAX_TRIES):
    storage.ack_outbox([failed_id], ok=False, err="找不到群")
assert rows()[failed_id]["status"] == "failed", rows()[failed_id]

assert storage.pending_targets("超英")[OLD]["total"] == 2, storage.pending_targets("超英")
assert storage.pending_targets("超英")[OLD]["failed"] == 1

# ---------- 主用例: 群改名后重绑定 ----------
r = storage.rebind_outbox_target("超英", NEW, old_target=OLD)
assert r["updated"] == 2 and r["merged"] == 0, r
assert r["old_targets"] == [OLD], r
assert r["to"] == NEW

cur = rows()
assert cur[ids[0]]["target"] == NEW and cur[ids[0]]["status"] == "pending"
assert cur[ids[1]]["target"] == NEW, "failed 的消息也应跟上新群名"
assert cur[ids[1]]["status"] == "pending" and cur[ids[1]]["tries"] == 0, "失败的应被重置为待发、可重试"
assert cur[ids[1]]["err"] == ""
assert cur[ids[2]]["target"] == "别的群", "old_target 之外的行不该动"
assert cur[ids[4]]["target"] == OLD, "别的商户绝不该被动"
print("主用例 ok:", r)

# ---------- 幂等键已重算: 同内容按新群名再入队应被判重 ----------
assert enq("msg-1", NEW) == 0, "重绑定后幂等键必须跟着群名一起重算"
assert enq("msg-1", OLD) == 1, "旧群名已是另一条键, 不算重复"
print("幂等键重算 ok")

# 已经是新群名的行不该被"再改一遍"
assert storage.rebind_outbox_target("超英", NEW, old_target=NEW)["updated"] == 0

# ---------- 新群名下已有同内容 → 合并重复而不是报错 ----------
enq("msg-X2", "旧群名3")
enq("msg-X2", NEW)                      # 同一条内容, 新群名下已有一条
r4 = storage.rebind_outbox_target("超英", NEW, old_target="旧群名3")
assert r4["updated"] == 0 and r4["merged"] == 1, r4
left = [i for i in rows().values() if i["content"] == "msg-X2" and i["target"] == NEW]
assert len(left) == 1, "重复行应被合并成一条"
print("合并重复 ok:", r4)

# ---------- retry_failed=False 时失败记录保持失败 ----------
enq("msg-F", OLD)
fid = [i for i in rows().values() if i["content"] == "msg-F"][0]["id"]
for _ in range(storage.MAX_TRIES):
    storage.ack_outbox([fid], ok=False, err="找不到群")
storage.rebind_outbox_target("超英", NEW, old_target=OLD, retry_failed=False)
assert rows()[fid]["status"] == "failed" and rows()[fid]["target"] == NEW, rows()[fid]
print("retry_failed=False ok")

# ---------- 空新群名要报错, 不能把消息改成"发给空群" ----------
try:
    storage.rebind_outbox_target("超英", "   ", old_target=NEW)
    raise AssertionError("新群名为空时必须报错")
except ValueError:
    print("空群名拦截 ok")

# ---------- 商户改名: 队列记录跟着改, 不会在界面上消失 ----------
n = storage.rename_outbox_merchant("尹欣", "尹欣美甲")
assert n == 1, n
assert storage.list_outbox(merchant="尹欣")["total"] == 0
assert storage.list_outbox(merchant="尹欣美甲")["total"] == 1
assert storage.rename_outbox_merchant("不存在", "x") == 0
assert storage.rename_outbox_merchant("x", "x") == 0
print("商户改名 ok")

# ---------- 后台侧: 群名一变自动重绑定 ----------
enq("auto-1", "老名字", merchant="门店A")
old_g = {"门店A": "老名字", "门店B": "B群"}
new_g = {"门店A": "新名字", "门店B": "B群"}
rebinds = web_admin._rebind_changed(old_g, new_g)
assert len(rebinds) == 1 and rebinds[0]["merchant"] == "门店A", rebinds
assert rebinds[0]["from"] == "老名字" and rebinds[0]["to"] == "新名字"
assert web_admin._rebind_changed(old_g, old_g) == [], "群名没变就不该有任何动作"
assert web_admin._rebind_changed({"门店A": "老名字"}, {"门店A": ""}) == [], "群名被清空时不动队列"
assert web_admin._rebind_changed(old_g, new_g, only="门店B") == [], "only 过滤要生效"
print("后台自动重绑定 ok:", rebinds)

# ---------- 绑定体检: 一眼看出队列里还残留着哪些旧群名 ----------
enq("stale-1", "早就改掉的名字", merchant="门店A")
web_admin._load_cfg = lambda: {
    "merchants": [{"name": "门店A", "account_id": "acc-1",
                   "wecom": {"target": "outbox", "wechat_group": "新名字"}}]
}
b = web_admin.api_group_binding()["bindings"]
assert len(b) == 1 and b[0]["merchant"] == "门店A", b
assert b[0]["configured_group"] == "新名字", b[0]
assert b[0]["queued_targets"]["新名字"]["total"] == 1, b[0]
assert b[0]["stale_targets"] == {"早就改掉的名字": {"pending": 1, "failed": 0, "total": 1}}, b[0]
assert b[0]["stale_total"] == 1 and b[0]["ok_total"] == 1, b[0]
print("绑定体检 ok:", b[0]["stale_targets"])

print("--- 群改名重新绑定 全部断言通过 ---")

gc.collect()          # 释放 sqlite 句柄(Windows 上文件被占用时删不掉, 属正常)
try:
    os.remove(tmp)
except OSError:
    pass

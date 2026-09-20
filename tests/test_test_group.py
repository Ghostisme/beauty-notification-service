# -*- coding: utf-8 -*-
"""链路测试消息(发到测试群)回归测试。

红线: 测试消息只能进【测试群】, 绝不能误发到任何门店群;
     也绝不能被门店的「群名重绑定」带走。

运行: python tests/test_test_group.py   (使用临时库, 不影响 data/admin.db)
"""
import gc
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage

tmp = os.path.join(tempfile.gettempdir(), "testgroup_test.db")
if os.path.exists(tmp):
    os.remove(tmp)
storage.DB_PATH = tmp
storage.init()

import sync      # noqa: E402
import web_admin  # noqa: E402

TEST_GROUP = "抖音本地生活订单通知"
REAL_GROUP = "玥笙-辽宁-大连中山店"


def rows():
    return {it["id"]: it for it in storage.list_outbox(page_size=200)["items"]}


# ---------- 测试文案本身 ----------
t = sync.build_test_message(TEST_GROUP)
assert TEST_GROUP in t, t
assert "🧪" in t and "中继" in t, t
assert len(t.splitlines()) >= 4
assert sync.build_test_message("") != "", "群名缺省也要能生成"
assert sync.build_test_message(TEST_GROUP) != sync.build_test_message(TEST_GROUP), \
    "毫秒级时间戳: 连点两次不能被队列的幂等键当成重复内容吞掉"

# ---------- 没配测试群就报错, 不能瞎发 ----------
try:
    sync.enqueue_test_message({"test_group": ""})
    raise AssertionError("没有测试群名时必须报错")
except ValueError as e:
    assert "测试群" in str(e), e
assert storage.outbox_stats().get("pending", 0) == 0, "报错时不该往队列里塞东西"

# ---------- 正常入队: 目标必须是测试群 ----------
res = sync.enqueue_test_message({"test_group": TEST_GROUP})
assert res["enqueued"] == 1 and res["target"] == TEST_GROUP, res
assert res["id"] and storage.list_outbox(page_size=5)["items"][0]["id"] == res["id"], \
    "要能精确拿到刚入队那条的 id, 方便只删它"
it = list(rows().values())[0]
assert it["target"] == TEST_GROUP, it
assert it["channel"] == "test", it
assert it["merchant"] == sync.TEST_MERCHANT, it
assert it["account_id"] == "", "测试消息不该挂到任何来客账户上"
print("入队 ok:", it["merchant"], "->", it["target"])

# 临时指定群名优先于配置
res = sync.enqueue_test_message({"test_group": TEST_GROUP}, group="另一个测试群")
assert res["target"] == "另一个测试群", res

# ---------- 红线: 门店群名重绑定不能把测试消息带走 ----------
storage.enqueue_outbox(["门店真订单"], merchant="门店A", account_id="acc-1",
                       channel="wechat_group", target=REAL_GROUP)
r = storage.rebind_outbox_target("门店A", "玥笙-辽宁-大连中山店(新)", old_target=REAL_GROUP)
assert r["updated"] == 1, r
after = rows()
test_rows = [x for x in after.values() if x["channel"] == "test"]
assert len(test_rows) == 2, test_rows
assert all(x["target"] in (TEST_GROUP, "另一个测试群") for x in test_rows), \
    [x["target"] for x in test_rows]
print("重绑定不碰测试群 ok:", [x["target"] for x in test_rows])

# 后台「全部重新绑定」走的也是这条路径, 再确认一次: 门店那条跟着新群名走
assert REAL_GROUP not in storage.pending_targets("门店A"), "重绑定后不该还指着旧群名"
assert "玥笙-辽宁-大连中山店(新)" in storage.pending_targets("门店A")
assert storage.pending_targets(sync.TEST_MERCHANT) != {}, "测试消息仍在队列里"

# ---------- 后台接口 ----------
CFG = {"wecom": {"target": "outbox", "test_group": TEST_GROUP}, "merchants": []}
saved = {}
web_admin._load_cfg = lambda: CFG
web_admin._save_cfg = lambda c: saved.update(c)

j = web_admin.api_outbox_test({})
assert j["enqueued"] == 1 and j["target"] == TEST_GROUP, j
print("接口(用配置里的测试群) ok:", j["target"])

j = web_admin.api_outbox_test({"group": "临时测试群"})
assert j["target"] == "临时测试群" and j["enqueued"] == 1, j
assert j.get("saved_test_group") == "临时测试群", j
assert saved.get("wecom", {}).get("test_group") == "临时测试群", saved

# 同一个群名再点一次不该重复保存配置
saved.clear()
j = web_admin.api_outbox_test({"group": "临时测试群"})
assert "saved_test_group" not in j and not saved, j

# ---------- 门店的自动重绑定不会顺手动测试群那几条 ----------
old_g = {"门店A": REAL_GROUP}
new_g = {"门店A": "玥笙-辽宁-大连中山店(新)"}
assert web_admin._rebind_changed(old_g, new_g) == [], "已经改过了, 不该再改一次"

print("--- 测试群链路消息 全部断言通过 ---")

gc.collect()
try:
    os.remove(tmp)
except OSError:
    pass

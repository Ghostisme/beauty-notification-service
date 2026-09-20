# -*- coding: utf-8 -*-
"""待发队列(outbox)全链路回归测试: 入队幂等 / 取件 / 回报 / 重试上限 / 重发 / 删除。

运行: python tests/test_outbox.py      (使用临时库, 不影响 data/admin.db)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage

tmp = os.path.join(tempfile.gettempdir(), "outbox_test.db")
if os.path.exists(tmp):
    os.remove(tmp)
storage.DB_PATH = tmp
storage.init()

c1 = "📣【新线索提醒】\n商户：超英皮肤定制管理\n客户手机：138****8000"
c2 = "🛍️【新订单提醒】\n订单号：1119125049613464779\n金额：¥199.00"

n1 = storage.enqueue_outbox([c1, c2], merchant="超英", account_id="7605435122824890377",
                            channel="wechat_group", target="美业客户服务群")
assert n1 == 2, f"首次入队应为2, 实际 {n1}"

n2 = storage.enqueue_outbox([c1, c2], merchant="超英", account_id="7605435122824890377",
                            channel="wechat_group", target="美业客户服务群")
assert n2 == 0, f"重复入队应被幂等去重, 实际 {n2}"

pend = storage.list_outbox(status="pending")
assert pend["total"] == 2, pend
ids = [it["id"] for it in pend["items"]]

# 中继回报: 第一条成功, 第二条失败
storage.ack_outbox([ids[0]], ok=True)
storage.ack_outbox([ids[1]], ok=False, err="群不存在")
mid = {it["id"]: it for it in storage.list_outbox()["items"]}
assert mid[ids[0]]["status"] == "sent", mid[ids[0]]
assert mid[ids[1]]["status"] == "pending" and mid[ids[1]]["tries"] == 1, mid[ids[1]]

# 连续失败到上限 → failed
for _ in range(4):
    storage.ack_outbox([ids[1]], ok=False, err="群不存在")
items = {it["id"]: it for it in storage.list_outbox()["items"]}
assert items[ids[1]]["status"] == "failed", items[ids[1]]
assert items[ids[1]]["tries"] == 5, items[ids[1]]

# 失败内容再次入队 → 自动重置为 pending
assert storage.enqueue_outbox([c2], account_id="7605435122824890377",
                              channel="wechat_group", target="美业客户服务群") == 1
assert {it["id"]: it for it in storage.list_outbox()["items"]}[ids[1]]["status"] == "pending"

# 手工重发 + 删除
assert storage.retry_outbox([ids[0]]) == 1
assert storage.delete_outbox([ids[0]]) == 1

stats = storage.outbox_stats()
print("outbox_stats =", json.dumps(stats, ensure_ascii=False))

# 多群/多商户隔离
storage.enqueue_outbox(["你好"], merchant="尹欣", account_id="7523898493467904038",
                       channel="wechat_group", target="尹欣客户群")
assert storage.list_outbox(merchant="尹欣")["total"] == 1
assert storage.list_outbox(merchant="超英")["total"] == 1

# 消息构建 -> 入队 联动
import sync
msgs = sync.build_messages(
    [{"order_id": "1119125049613464779", "goods": "小气泡清洁", "amount": "199",
      "status": "已完成", "phone": "13812348000", "customer": "张女士",
      "created_at": "2026-09-20 12:00:00", "shop": "超英皮肤定制"}],
    {"template": "order", "per_order": False, "fields": ["order_id", "goods", "amount", "phone"]})
assert msgs and "订单汇总提醒" in msgs[0]["markdown"]["content"], msgs
print("--- 生成文案预览 ---")
print(sync.md_to_text(msgs[0]["markdown"]["content"]))
print("--- 所有断言通过 ---")

os.remove(tmp)

"""完全离线的独立演示数据；不使用真实平台凭证或发送端。"""
import time
import uuid

from .db import dumps


class DemoClient:
    def orders(self, account_id, start, end, max_pages):
        yield order(account_id, "demo-poi-1" if account_id == "demo-1001" else "demo-poi-3",
                    "DEMO-" + uuid.uuid4().hex[:12].upper(), time.time() - 30)

    def decrypt_orders(self, orders, account_id):
        return orders, ""


def order(account, poi, record, at):
    return {"order_id": record, "merchant_info": {"account_id": account}, "poi": {"poi_id": poi},
            "contacts": [{"name": "示例客户", "phone": "138****0000"}],
            "products": [{"snapshot_product": {"product_name": "面部补水护理套餐"}}], "count": 1,
            "pay_amount": 9900, "order_status": 201, "create_order_time": at - 30, "pay_time": at,
            "update_order_time": at, "certificate": [{"certificate_id": record + "-C1", "item_status": 100}]}


def seed(app):
    db, engine = app.extensions["db"], app.extensions["engine"]
    marker = db.directory / ".demo-mode"
    if not marker.exists() and db.one("SELECT COUNT(*) AS n FROM enterprises")["n"]:
        raise RuntimeError("演示模式只能使用空目录或已有演示目录，请使用 --demo 的默认目录")
    engine.client = DemoClient()
    if marker.exists():
        return
    marker.write_text("offline-demo\n", encoding="utf-8")
    now = time.time()
    with db.connect(write=True) as c:
        for account, name in (("demo-1001", "玥笙美业 · 示例企业"), ("demo-1002", "壹心美业 · 示例企业")):
            c.execute("INSERT INTO enterprises(account_id,name,created_at,last_sync) VALUES (?,?,?,?)", (account, name, now - 86400, now - 120))
        for ent, poi, name, group in ((1, "demo-poi-1", "玥笙-辽宁-大连中山店", "demo-group-1"),
                                     (1, "demo-poi-2", "玥笙-辽宁-沈阳沈河店", "demo-group-2"),
                                     (2, "demo-poi-3", "壹心-湖南-长沙开福店", "demo-group-3"),
                                     (2, "demo-poi-4", "壹心-湖南-长沙雨花店", "demo-group-4")):
            c.execute("INSERT INTO stores(enterprise_id,poi_id,name,group_id,group_name,created_at) VALUES (?,?,?,?,?,?)", (ent, poi, name, group, name, now))
    for i in range(64):
        account = "demo-1001" if i % 2 == 0 else "demo-1002"
        poi = "demo-poi-1" if i % 2 == 0 else "demo-poi-3"
        at = now - (64 - i) * 50
        if i in (59, 62):
            poi = "demo-unbound-poi"
        if i % 4 == 0:
            result = engine.ingest_event({"account_id": account, "type": "new_lead", "poi_id": poi,
                "record_id": f"LEAD-DEMO-{i:04d}", "event_time": at,
                "data": {"customer": "示例客户", "phone": "138****0000", "intent": "面部护理",
                         "source": "演示留资表单", "remark": "希望周末到店"}}, now=at)
            message_id = result["message_id"]
        elif i % 7 == 0:
            result = engine.ingest_event({"account_id": account, "type": "status_change", "event": "verified",
                "event_id": f"DEMO-VERIFIED-{i}", "record_id": f"DY-DEMO-{i:04d}", "poi_id": poi,
                "event_time": at, "data": {"customer": "示例客户", "phone": "138****0000",
                    "goods": "面部补水护理套餐", "previous_status": "待使用", "current_status": "已核销"}}, now=at)
            message_id = result["message_id"]
        else:
            result = engine.ingest_order(account, order(account, poi, f"DY-DEMO-{i:04d}", at), now=at)
            message_id = result["notifications"][0]["message_id"]
        if i < 48 or i in (51, 53, 55):
            with db.connect(write=True) as c:
                c.execute("UPDATE messages SET status='sent',sent_at=?,result_source='demo',attempts=1 WHERE id=?", (at + 8, message_id))
        elif i in (48, 52):
            with db.connect(write=True) as c:
                c.execute("UPDATE messages SET status='uncertain',last_error='演示：发送后连接中断，请核实群内是否收到',attempts=1 WHERE id=?", (message_id,))
        elif i == 56:
            with db.connect(write=True) as c:
                c.execute("UPDATE messages SET status='failed',last_error='演示：未找到唯一匹配的接收群',attempts=5 WHERE id=?", (message_id,))
    with db.connect(write=True) as c:
        for i in range(5):
            details = [{"enterprise": "玥笙美业 · 示例企业", "orders": 8, "queued": 3},
                       {"enterprise": "壹心美业 · 示例企业", "orders": 6, "queued": 2}]
            c.execute("INSERT INTO task_runs(trigger,status,started_at,finished_at,orders,queued,details) VALUES ('scheduled','success',?,?,14,5,?)", (now - 600 + i * 120, now - 598 + i * 120, dumps(details)))
    db.audit("创建离线演示数据")

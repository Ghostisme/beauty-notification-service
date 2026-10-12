import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from toolbox.engine import Conflict
from .conftest import delivery, lead


def test_order_has_exact_store_template_and_safe_phone(engine, db, order):
    result = engine.ingest_order("1001", order)
    message = engine.message_detail(result["notifications"][0]["message_id"])
    assert message["group_id"] == "g1"
    assert "门店：玥笙-辽宁-大连中山店" in message["body"]
    assert "团购项目：补水护理" in message["body"]
    assert "实付金额：¥199.01" in message["body"]
    assert "联系电话" not in message["body"] and "Enc." not in message["body"]
    assert engine.ingest_order("1001", order)["queued"] == 0
    assert db.one("SELECT COUNT(*) n FROM messages")["n"] == 1


def test_tenants_same_order_and_poi_are_isolated(engine, db, order):
    engine.ingest_order("1001", order)
    other = copy.deepcopy(order)
    other["merchant_info"]["account_id"] = "1002"
    engine.ingest_order("1002", other)
    assert [r["group_id"] for r in db.rows("SELECT group_id FROM messages ORDER BY id")] == ["g1", "g2"]
    with pytest.raises(ValueError, match="商户账号"):
        engine.ingest_order("1002", order)


def test_unknown_store_requires_same_tenant_manual_route(engine, db):
    result = engine.ingest_event(lead(poi="unknown"))
    row = engine.message_detail(result["message_id"])
    assert row["status"] == "unrouted"
    with pytest.raises(ValueError, match="本企业"):
        engine.manual_action(row["id"], "route", {"version": row["version"], "store_id": 2})
    routed = engine.manual_action(row["id"], "route", {"version": row["version"], "store_id": 1})
    assert routed["status"] == "pending" and routed["group_id"] == "g1"


def test_no_old_or_first_seen_verified_spam(engine, db, order):
    old = time.time() - 86400
    order.update(create_order_time=old - 30, pay_time=old, update_order_time=old)
    order["certificate"][0].update(item_status=401, item_update_time=old)
    result = engine.ingest_order("1001", order)
    assert result["notifications"][0]["status"] == "skipped_old"
    assert db.one("SELECT COUNT(*) n FROM messages")["n"] == 1


def test_paid_transition_only_one_new_order(engine, db, order):
    order["order_status"] = 100
    assert engine.ingest_order("1001", order)["queued"] == 0
    rules = db.settings("notifications")
    db.set_settings("notifications", {**rules, "status_events": ["paid", "verified"]})
    order["order_status"] = 201
    order["update_order_time"] += 1
    assert engine.ingest_order("1001", order)["queued"] == 1
    assert db.one("SELECT COUNT(*) n FROM messages")["n"] == 1


def test_certificate_status_change_and_duplicate_and_older_snapshot(engine, db, order):
    engine.ingest_order("1001", order)
    earlier = copy.deepcopy(order)
    order["certificate"][0].update(item_status=401, item_update_time=int(time.time()) - 10)
    order["update_order_time"] += 10
    result = engine.ingest_order("1001", order)
    assert result["queued"] == 1
    assert engine.ingest_order("1001", order)["queued"] == 0
    assert engine.ingest_order("1001", earlier)["ignored"] == "older_snapshot"
    assert db.one("SELECT COUNT(*) n FROM messages WHERE category='status_change'")["n"] == 1


def test_finished_is_not_automatically_verified(engine, db, order):
    engine.ingest_order("1001", order)
    order.update(order_status=1, update_order_time=order["update_order_time"] + 1)
    assert engine.ingest_order("1001", order)["queued"] == 0


def test_lead_dedup_separate_from_order(engine, db, order):
    engine.ingest_order("1001", order)
    event = lead(record=order["order_id"])
    assert engine.ingest_event(event)["queued"] == 1
    assert engine.ingest_event(event)["duplicate"]
    assert db.one("SELECT COUNT(*) n FROM messages")["n"] == 2


def test_notification_disable_keeps_record_without_sending(engine, db):
    with db.connect(write=True) as c:
        c.execute("UPDATE templates SET enabled=0 WHERE kind='new_lead'")
    result = engine.ingest_event(lead())
    assert result["status"] == "muted"
    delivery(db)
    assert engine.claim("w") is None


def test_claim_gate_group_filter_and_rebinding(engine, db):
    engine.ingest_event(lead())
    assert engine.claim("w") is None
    delivery(db)
    assert engine.claim("w", []) is None
    with db.connect(write=True) as c:
        c.execute("UPDATE stores SET group_id='changed' WHERE id=1")
    assert engine.claim("w") is None
    assert db.one("SELECT status FROM messages")["status"] == "unrouted"


def test_group_filter_does_not_starve_after_other_groups(engine, db):
    for i in range(105):
        engine.ingest_event(lead(record=f"A-{i}"))
    engine.ingest_event(lead(record="B", account="1002"))
    delivery(db)
    assert engine.claim("worker-b", ["g2"])["group_id"] == "g2"


def test_concurrent_claims_never_claim_same_job(engine, db):
    for i in range(12):
        engine.ingest_event(lead(record=f"C-{i}"))
    delivery(db)
    with ThreadPoolExecutor(6) as pool:
        jobs = list(pool.map(lambda i: engine.claim(f"w{i}"), range(12)))
    assert len({job["id"] for job in jobs}) == 12


def test_expired_lease_uncertain_and_late_same_attempt_can_confirm(engine, db):
    engine.ingest_event(lead())
    delivery(db)
    job = engine.claim("w")
    with db.connect(write=True) as c:
        c.execute("UPDATE messages SET lease_until=?", (time.time() - 1,))
    assert engine.recover() == 1
    assert engine.claim("w") is None
    result = engine.finish(job["id"], job["lease_token"], "sent", group_id="g1")
    assert result["status"] == "sent"
    assert engine.finish(job["id"], job["lease_token"], "sent", group_id="g1")["duplicate_receipt"]


def test_wrong_group_or_attempt_never_marks_sent(engine, db):
    engine.ingest_event(lead())
    delivery(db)
    job = engine.claim("w")
    with pytest.raises(Conflict):
        engine.finish(job["id"], "bad-lease", "sent", group_id="g1")
    assert engine.finish(job["id"], job["lease_token"], "sent", group_id="g2")["status"] == "uncertain"


def test_explicit_failed_backoff_and_manual_retry_generation(engine, db):
    result = engine.ingest_event(lead())
    delivery(db)
    job = engine.claim("w")
    result = engine.finish(job["id"], job["lease_token"], "failed", "确认没有发送")
    assert result["status"] == "pending" and result["next_attempt"] > time.time()
    assert engine.claim("w") is None
    row = engine.message_detail(job["id"])
    engine.manual_action(row["id"], "retry", {"version": row["version"]})
    next_job = engine.claim("w")
    assert next_job["idempotency_key"] != job["idempotency_key"]
    with pytest.raises(Conflict):
        engine.finish(job["id"], job["lease_token"], "sent", group_id="g1")


def test_uncertain_requires_note_and_optimistic_version(engine, db):
    result = engine.ingest_event(lead())
    delivery(db)
    job = engine.claim("w")
    engine.finish(job["id"], job["lease_token"], "uncertain")
    row = engine.message_detail(result["message_id"])
    with pytest.raises(ValueError, match="核实"):
        engine.manual_action(row["id"], "retry", {"version": row["version"]})
    row2 = engine.manual_action(row["id"], "retry", {"version": row["version"], "note": "在门店群核实，确认未发送"})
    assert row2["status"] == "pending"
    with pytest.raises(Conflict):
        engine.manual_action(row["id"], "cancel", {"version": row["version"]})


def test_retention_keeps_dedup_and_does_not_reuse_message_id(engine, db):
    event = lead()
    result = engine.ingest_event(event)
    old_id = result["message_id"]
    with db.connect(write=True) as c:
        c.execute("UPDATE messages SET status='sent',updated_at=?", (time.time() - 100 * 86400,))
    assert db.cleanup() == 1
    assert engine.ingest_event(event)["duplicate"]
    assert engine.ingest_event(lead(record="L2"))["message_id"] > old_id


def test_sync_cursor_failure_isolated_and_no_concurrent_runs(engine, db, order):
    class Client:
        def orders(self, account_id, *args):
            if account_id == "1001":
                raise RuntimeError("测试：企业授权失败")
            other = copy.deepcopy(order);other["merchant_info"]["account_id"] = account_id
            yield other
        def decrypt_orders(self, records, account_id):return records, ""
    engine.client = Client()
    result = engine.run_sync()
    assert result["status"] == "partial" and result["orders"] == 1
    assert db.one("SELECT sync_cursor FROM enterprises WHERE id=1")["sync_cursor"] is None
    assert db.one("SELECT sync_cursor FROM enterprises WHERE id=2")["sync_cursor"]
    engine.sync_lock.acquire()
    try:
        with pytest.raises(Conflict):engine.run_sync()
    finally:engine.sync_lock.release()


def test_slow_sync_does_not_block_scheduler_or_dispatch(engine, db):
    entered, release = threading.Event(), threading.Event()
    class Client:
        def orders(self,*args):
            entered.set();release.wait(3);yield from []
        def decrypt_orders(self,records,*args):return records,""
    engine.client = Client()
    engine.start();engine.launch_sync()
    assert entered.wait(2)
    tick = engine.last_tick
    time.sleep(1.2)
    try:assert engine.last_tick > tick
    finally:release.set()

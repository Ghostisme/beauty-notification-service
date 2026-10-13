import copy
import json
import time

import pytest

from toolbox.domain import full_phone, normalize_clue, normalize_order, time_text
from toolbox.douyin import DouyinClient, PlatformError
from toolbox.engine import Conflict
from .conftest import delivery


def clue(identifier="CL-1", account="1001", poi="p1", order_id="DY-001", phone="13800000000"):
    return {"clue_id": identifier, "root_life_account_id": account, "intention_poi_id": poi,
            "follow_poi_id": poi, "order_id": order_id, "create_time_detail": time_text(time.time() - 1200),
            "phone": phone, "name": "线索客户", "product_name": "护理", "enc_telephone": "Enc." + identifier}


def require_phone(db):
    db.set_settings("notifications", {**db.settings("notifications"), "require_full_phone": True})


def test_masked_phone_is_not_a_full_contact_and_decrypted_field_wins(order):
    order["contacts"] = [{"phone": "138****0000", "phone_encrypt": "13800000000"}]
    assert normalize_order(order)["phone"] == "13800000000"
    order["contacts"][0].pop("phone_encrypt")
    normalized = normalize_order(order)
    assert not normalized["phone_available"] and normalized["phone_state"] == "masked"
    assert full_phone("+86 138-0000-0000") == "13800000000"
    assert not full_phone("138****0000")


def test_batch_contract_matches_cipher_and_never_accepts_failed_or_foreign_results(db):
    client = DouyinClient(db)
    calls = []
    def request(method, path, account, params=None, body=None):
        calls.append(body)
        return {"results": [
            {"cipher_text": "Enc.good", "plain_text": "13800000000", "is_success": True},
            {"cipher_text": "Enc.failed", "plain_text": "13900000000", "is_success": False, "error_code": 403},
            {"cipher_text": "Enc.foreign", "plain_text": "13700000000", "is_success": True}]}
    client.request = request
    result, warning = client.decrypt_values(["Enc.good", "Enc.good", "Enc.failed", "138****0000"], "1001")
    assert calls == [{"account_id": "1001", "cipher_texts": ["Enc.good", "Enc.failed"]}]
    assert result == {"Enc.good": "13800000000"} and "403" in warning
    client.decrypt_values(["Enc.good"], "1001")
    assert len(calls) == 1
    client.decrypt_values(["Enc.good"], "1002")
    assert len(calls) == 2


def test_clue_pagination_contract_and_stable_identifiers(db):
    client = DouyinClient(db)
    calls = []
    def request(method, path, account, params=None, body=None):
        calls.append(params)
        return {"clue_data": [clue(str(i)) for i in (range(100) if len(calls) == 1 else [100])],
                "page": {"total": 101}}
    client.request = request
    assert len(list(client.clues("1001", 1778515200, 1778601600))) == 101
    assert calls[0]["start_time"] == "2026-05-12 00:00:00" and calls[1]["page"] == 2
    client.request = lambda *a, **k: {"clue_data": [clue()], "page": {"total": 2}}
    with pytest.raises(RuntimeError, match="重复"):
        list(client.clues("1001", 1, 2))
    with pytest.raises(ValueError, match="365"):
        list(client.clues("1001", 1, 366 * 86400))


def test_clue_cannot_change_merchant_identity_or_invent_a_current_timestamp():
    with pytest.raises(ValueError, match="商户"):
        normalize_clue(clue(account="1002"), "1001")
    raw = clue()
    raw["create_time_detail"] = "invalid"
    with pytest.raises(ValueError, match="创建时间"):
        normalize_clue(raw, "1001")


@pytest.mark.parametrize("response", [
    {"error_code": 0, "description": "success"}, {"clue_data": [], "page": {"total": 0}}])
def test_real_empty_clue_window_is_success(db, response):
    client = DouyinClient(db)
    client.request = lambda *a, **k: response
    assert list(client.clues("1001", 1, 2)) == []


@pytest.mark.parametrize("response", [{}, {"clue_data": None}, {"clue_data": "bad"}, {"error_code": 0, "unknown": []}])
def test_malformed_clue_response_is_not_mistaken_for_an_empty_window(db, response):
    client = DouyinClient(db)
    client.request = lambda *a, **k: response
    with pytest.raises(RuntimeError, match="clue_data"):
        list(client.clues("1001", 1, 2))


@pytest.mark.parametrize("last_page", [{"error_code": 0, "description": "success"}, {"clue_data": [], "page": {"total": 101}}])
def test_empty_page_cannot_silently_discard_expected_clues(db, last_page):
    client = DouyinClient(db)
    pages = iter([{"clue_data": [clue(str(i)) for i in range(100)], "page": {"total": 101}}, last_page])
    client.request = lambda *a, **k: next(pages)
    with pytest.raises(RuntimeError, match="提前结束"):
        list(client.clues("1001", 1, 2))


def test_successful_empty_merchant_and_failed_merchant_report_partial(engine):
    class Client:
        def orders(self, account, *args):
            if account == "1002":
                raise PlatformError(2119005, "未授权")
            return iter([])
    engine.client = Client()
    result = engine.run_sync()
    assert result["orders"] == 0 and result["status"] == "partial" and result["errors"] == 1


def test_order_joins_full_phone_only_with_same_merchant_order_and_store(engine, db, order):
    require_phone(db)
    engine.ingest_event(normalize_clue(clue(account="1002"), "1002"))
    engine.ingest_event(normalize_clue(clue("wrong-store", poi="other"), "1001"))
    result = engine.ingest_order("1001", order)
    assert result["notifications"][0]["status"] == "waiting_phone"
    engine.ingest_event(normalize_clue(clue("right"), "1001"))
    assert engine.refresh_waiting_phones(1, ["DY-001"]) == 1
    message = engine.message_detail(result["notifications"][0]["message_id"])
    assert message["status"] == "pending" and "13800000000" in message["body"]
    assert message["payload"]["phone_source"] == "douyin_clue"


def test_conflicting_full_contacts_are_not_selected_by_first_match(engine, db, order):
    require_phone(db)
    for identifier, phone in (("A", "13800000000"), ("B", "13900000000")):
        engine.ingest_event(normalize_clue(clue(identifier, phone=phone), "1001"))
    result = engine.ingest_order("1001", order)
    message = engine.message_detail(result["notifications"][0]["message_id"])
    assert message["status"] == "waiting_phone" and message["payload"]["phone_state"] == "ambiguous"
    assert "13800000000" not in message["body"] and "13900000000" not in message["body"]


def test_same_contact_with_country_code_is_not_a_conflict(engine, db, order):
    require_phone(db)
    for identifier, phone in (("A", "13800000000"), ("B", "+86 138-0000-0000")):
        engine.ingest_event(normalize_clue(clue(identifier, phone=phone), "1001"))
    result = engine.ingest_order("1001", order)
    row = engine.message_detail(result["notifications"][0]["message_id"])
    assert row["status"] == "pending" and row["payload"]["phone"] == "13800000000"


def test_later_conflicting_clue_blocks_a_previously_ready_order_at_claim(engine, db, order):
    require_phone(db)
    with db.connect(write=True) as c:
        c.execute("UPDATE templates SET enabled=0 WHERE kind='new_lead'")
    engine.ingest_event(normalize_clue(clue("A"), "1001"))
    result = engine.ingest_order("1001", order)
    engine.ingest_event(normalize_clue(clue("B", phone="13900000000"), "1001"))
    delivery(db)
    assert engine.claim("sender") is None
    row = engine.message_detail(result["notifications"][0]["message_id"])
    assert row["status"] == "waiting_phone" and row["payload"]["phone_state"] == "ambiguous"
    assert "13800000000" not in row["body"] and "13900000000" not in row["body"]


def test_claim_preserves_manual_lead_text_when_only_phone_metadata_refreshes(engine, db):
    require_phone(db)
    result = engine.ingest_event(normalize_clue(clue(), "1001"))
    message = engine.message_detail(result["message_id"])
    edited = "【真实历史留资联调】\n此消息用于测试，无需业务处理。\n" + message["body"]
    engine.manual_action(message["id"], "edit", {"version": message["version"], "body": edited})
    delivery(db)

    job = engine.claim("sender")

    assert job["text"] == edited
    updated = engine.message_detail(message["id"])
    assert updated["body"] == edited and updated["payload"]["phone_available"] is True


def test_claim_still_updates_phone_when_authoritative_lead_number_changes(engine, db):
    require_phone(db)
    result = engine.ingest_event(normalize_clue(clue(), "1001"))
    engine.ingest_event(normalize_clue(clue(phone="13900000000"), "1001"))
    delivery(db)

    job = engine.claim("sender")

    assert job["id"] == result["message_id"]
    assert "13900000000" in job["text"] and "13800000000" not in job["text"]
    assert engine.message_detail(job["id"])["payload"]["phone"] == "13900000000"


@pytest.mark.parametrize("change,expected", [
    ("age", "skipped_old"), ("store", "blocked"), ("template", "muted"), ("group", "unrouted")])
@pytest.mark.parametrize("automatic", [True, False])
def test_phone_completion_rechecks_age_pause_template_and_group(engine, db, order, change, expected, automatic):
    require_phone(db)
    result = engine.ingest_order("1001", order)
    message_id = result["notifications"][0]["message_id"]
    with db.connect(write=True) as c:
        if change == "age":
            c.execute("UPDATE events SET event_time=?", (time.time() - 86400,))
        elif change == "store":
            c.execute("UPDATE stores SET enabled=0 WHERE id=1")
        elif change == "template":
            c.execute("UPDATE templates SET enabled=0 WHERE kind='new_order'")
        else:
            c.execute("UPDATE stores SET group_name='新的群名' WHERE id=1")
    if automatic:
        engine.ingest_event(normalize_clue(clue(), "1001"))
        assert engine.refresh_waiting_phones(1, ["DY-001"]) == 0
    else:
        engine.manual_action(message_id, "contact", {"version": 1, "phone": "13800000000", "note": "门店核对"})
    assert engine.message_detail(message_id)["status"] == expected
    assert db.one("SELECT COUNT(*) n FROM attempts")["n"] == 0


def test_legacy_decryption_uses_the_documented_last_sixteen_bytes_iv(db):
    # 固定密文由 Node.js crypto 独立生成；与生产实现共用算法但不共用代码。
    assert DouyinClient.decrypt_legacy("DZgTyG6Q5uN9Rq9PnlMHgA==", "test-legacy-key") == "13800000000"
    assert DouyinClient(db).session.trust_env is False


def test_require_phone_rechecks_an_existing_pending_message_before_sender_claim(engine, db, order):
    result = engine.ingest_order("1001", order)
    delivery(db)
    require_phone(db)
    assert engine.claim("sender") is None
    assert engine.message_detail(result["notifications"][0]["message_id"])["status"] == "waiting_phone"
    assert db.one("SELECT COUNT(*) n FROM attempts")["n"] == 0


def test_manual_contact_validates_and_audits_without_sending(engine, db, order):
    require_phone(db)
    result = engine.ingest_order("1001", order)
    message_id = result["notifications"][0]["message_id"]
    row = engine.message_detail(message_id)
    with pytest.raises(ValueError, match="完整手机号"):
        engine.manual_action(message_id, "contact", {"version": row["version"], "phone": "138****0000", "note": "门店核对"})
    updated = engine.manual_action(message_id, "contact", {"version": row["version"], "phone": "13800000000", "note": "门店核对"})
    assert updated["status"] == "pending" and "13800000000" in updated["body"]
    assert not updated["attempt_history"]
    assert updated["payload"]["phone_source"] == "manual"
    assert "13800000000" not in json.dumps(db.rows("SELECT * FROM audit"))
    with pytest.raises(Conflict):
        engine.manual_action(message_id, "contact", {"version": row["version"], "phone": "13900000000", "note": "过期版本"})


def test_native_clue_sync_decrypts_links_order_and_advances_separate_cursor(engine, db, order):
    require_phone(db)
    db.set_settings("douyin", {**db.settings("douyin"), "clue_enabled": True, "decrypt_enabled": True})
    class Client:
        def clues(self, account, start, end, max_pages):
            assert end <= time.time() - 590
            if account == "1001":
                yield clue()
        def decrypt_clues(self, records, account):
            return records, ""
        def orders(self, account, *args):
            if account == "1001":
                yield copy.deepcopy(order)
        def decrypt_orders(self, records, account):
            return records, ""
    engine.client = Client()
    result = engine.run_sync()
    assert result["status"] == "success" and result["orders"] == 1
    assert result["details"][0]["full_phones"] == 1
    assert db.one("SELECT clue_cursor FROM enterprises WHERE id=1")["clue_cursor"]
    message = db.one("SELECT * FROM messages WHERE category='new_order'")
    assert "13800000000" in message["body"] and message["status"] == "pending"
    assert db.one("SELECT COUNT(*) n FROM attempts")["n"] == 0


def test_partial_decrypt_keeps_clue_cursor_for_retry_but_does_not_break_order_sync(engine, db, order):
    require_phone(db)
    db.set_settings("douyin", {**db.settings("douyin"), "clue_enabled": True, "decrypt_enabled": True})
    class Client:
        def clues(self, account, *args):
            if account == "1001":
                yield clue(phone="")
        def decrypt_clues(self, records, account):
            return records, "额度不足"
        def orders(self, account, *args):
            if account == "1001":
                yield order
        def decrypt_orders(self, records, account):
            return records, ""
    engine.client = Client()
    result = engine.run_sync()
    assert result["status"] == "partial" and result["orders"] == 1
    assert db.one("SELECT clue_cursor FROM enterprises WHERE id=1")["clue_cursor"] is None
    assert db.one("SELECT status FROM messages WHERE category='new_order'")["status"] == "waiting_phone"


def test_contact_settings_validation_and_api_are_authenticated(admin, db, engine, order, app):
    client, headers = admin
    bad = client.put("/api/config/douyin", json={"clue_enabled": True}, headers=headers)
    assert bad.status_code == 400
    response = client.put("/api/config/douyin", json={"clue_enabled": True, "decrypt_enabled": True}, headers=headers)
    assert response.status_code == 200
    require_phone(db)
    result = engine.ingest_order("1001", order)
    message_id = result["notifications"][0]["message_id"]
    path = f"/api/messages/{message_id}/contact"
    assert app.test_client().post(path, json={}).status_code == 401
    assert client.post(path, json={}).status_code == 403
    response = client.post(path, json={"version": 1, "phone": "13800000000", "note": "门店登记"}, headers=headers)
    assert response.status_code == 200 and response.json["payload"]["phone_state"] == "full"


def test_order_number_search_finds_linked_lead_without_creating_an_order_notification(admin, engine):
    engine.ingest_event(normalize_clue(clue(order_id="ORDER-ONLY-IN-LINK"), "1001"))
    client, _ = admin
    response = client.get("/api/messages?keyword=ORDER-ONLY-IN-LINK")
    assert response.status_code == 200 and response.json["total"] == 1
    assert response.json["items"][0]["category"] == "new_lead"

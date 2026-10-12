import copy
import time

import pytest

from toolbox.web import create_app

PASSWORD = "Test-only-20261012"


@pytest.fixture
def app(tmp_path):
    value = create_app(tmp_path / "data", password=PASSWORD)
    value.config.update(TESTING=True)
    db = value.extensions["db"]
    with db.connect(write=True) as c:
        for account, name in (("1001", "玥笙"), ("1002", "壹心")):
            c.execute("INSERT INTO enterprises(account_id,name,created_at) VALUES (?,?,?)", (account, name, time.time()))
        for ent, poi, name, group in ((1, "p1", "玥笙-辽宁-大连中山店", "g1"),
                                     (2, "p1", "壹心-湖南-长沙开福店", "g2")):
            c.execute("INSERT INTO stores(enterprise_id,poi_id,name,group_id,group_name,created_at) VALUES (?,?,?,?,?,?)", (ent, poi, name, group, name, time.time()))
    yield value
    value.extensions["engine"].stop()


@pytest.fixture
def db(app):
    return app.extensions["db"]


@pytest.fixture
def engine(app):
    return app.extensions["engine"]


@pytest.fixture
def admin(app):
    client = app.test_client()
    response = client.post("/api/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200
    return client, {"X-CSRF-Token": response.json["csrf"]}


@pytest.fixture
def order():
    now = int(time.time())
    return {"order_id": "DY-001", "merchant_info": {"account_id": "1001"}, "poi": {"poi_id": "p1"},
            "products": [{"snapshot_product": {"product_name": "补水护理"}}], "count": 2,
            "contacts": [{"name": "测试顾客", "phone_encrypt": "Enc.not-a-phone"}],
            "pay_amount": 19901, "order_status": 201, "create_order_time": now - 90,
            "pay_time": now - 60, "update_order_time": now - 30,
            "certificate": [{"certificate_id": "C1", "item_status": 100, "item_update_time": now - 30}]}


def delivery(db, enabled=True):
    db.set_settings("notifications", {**db.settings("notifications"), "delivery_enabled": enabled})


def lead(record="L1", account="1001", poi="p1"):
    return {"type": "new_lead", "account_id": account, "record_id": record, "poi_id": poi,
            "event_time": time.time(), "data": {"customer": "测试顾客", "phone": "13800000000", "intent": "护理"}}

import time

from .conftest import PASSWORD, delivery, lead


def test_auth_csrf_and_password_invalidates_sessions(app, admin):
    client, headers = admin
    assert app.test_client().get("/api/dashboard").status_code == 401
    assert client.post("/api/tasks/run", json={}).status_code == 403
    second = app.test_client()
    second.post("/api/login",json={"username":"admin","password":PASSWORD})
    assert client.post("/api/password",json={"current_password":PASSWORD,"new_password":"Replacement-20261012"},headers=headers).status_code == 200
    assert second.get("/api/dashboard").status_code == 401


def test_secrets_encrypted_and_not_returned(db, admin):
    client, headers = admin
    secret = "fixture-platform-secret-123456"
    assert client.put("/api/config/douyin",json={"client_key":"fixture-key","client_secret":secret},headers=headers).status_code == 200
    assert secret not in client.get("/api/config").get_data(as_text=True)
    assert secret not in db.one("SELECT value FROM secrets WHERE key='douyin_secret'")["value"]
    assert db.secret("douyin_secret") == secret


def test_bad_config_and_template_return_useful_400(admin):
    c,h=admin
    for data in ({"status_events":[{}]}, {"order_trigger":"whatever"}, {"delivery_enabled":"true"}):
        assert c.put("/api/config/notifications",json=data,headers=h).status_code == 400
    assert c.put("/api/templates/new_order",json={"body":"{客户称呼.__class__}","enabled":True},headers=h).status_code == 400
    assert c.put("/api/config/scheduler",json={"interval_seconds":0},headers=h).status_code == 400


def test_scoped_ingest_token_and_pagination(db, admin, app):
    c,h=admin
    token=db.secret("ingest_token")
    assert c.post("/api/ingest",json=lead()).status_code == 401
    assert c.post("/api/relay/heartbeat",json={},headers={"Authorization":"Bearer "+token}).status_code == 401
    for i in range(7):
        assert c.post("/api/ingest",json=lead(record=f"I-{i}"),headers={"Authorization":"Bearer "+token}).status_code == 200
    data=c.get("/api/messages?page=2&page_size=3").json
    assert data["total"]==7 and len(data["items"])==3
    assert c.get("/api/messages?keyword=%25").json["total"]==0


def test_relay_requires_recent_ready_heartbeat_and_success_group(app, db, engine):
    client=app.test_client();headers={"Authorization":"Bearer "+db.secret("relay_token")}
    engine.ingest_event(lead());delivery(db)
    assert client.post("/api/relay/claim",json={"worker_id":"w"},headers=headers).status_code==400
    assert client.post("/api/relay/heartbeat",json={"worker_id":"w","ready":True,"groups":["g1"]},headers=headers).status_code==200
    job=client.post("/api/relay/claim",json={"worker_id":"w"},headers=headers).json["job"]
    receipt={"message_id":job["id"],"lease_token":job["lease_token"],"status":"sent"}
    assert client.post("/api/relay/result",json=receipt,headers=headers).status_code==400
    receipt["group_id"]="g1"
    assert client.post("/api/relay/result",json=receipt,headers=headers).json["status"]=="sent"


def test_manual_lead_renders_phone_and_audits(admin, db):
    c,h=admin
    r=c.post("/api/manual/lead",json=lead(),headers=h)
    assert r.status_code==201
    msg=c.get('/api/messages/'+str(r.json['message_id'])).json
    assert '联系电话：13800000000' in msg['body']
    assert db.one("SELECT action FROM audit ORDER BY id DESC")["action"]=="手工录入留资"


def test_no_public_data_in_static_health_and_headers(app):
    c=app.test_client()
    assert set(c.get('/health').json)=={'status','version'}
    r=c.get('/')
    assert r.status_code==200 and 'script-src' in r.headers['Content-Security-Policy']
    assert c.get('/api/dashboard').headers['Cache-Control']=='no-store'

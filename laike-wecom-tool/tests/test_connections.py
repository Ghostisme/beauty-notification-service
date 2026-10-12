import time

from toolbox.connections import current_check, identity, save_check
from toolbox.douyin import PlatformError
from toolbox.testing import TEST_GROUP_ID, prepare_test_group
from toolbox.web import create_app

from .conftest import PASSWORD, lead


def items(client):
    response = client.get('/api/connections')
    assert response.status_code == 200
    return {item['key']: item for item in response.json['items']}


def credentials(db):
    db.set_settings('douyin', {**db.settings('douyin'), 'client_key': 'fixture-app-key'})
    db.set_secret('douyin_secret', 'fixture-app-secret')


def test_check_requires_admin_and_csrf(app, admin):
    client, _ = admin
    assert app.test_client().get('/api/connections').status_code == 401
    assert client.post('/api/connections/douyin/check', json={}).status_code == 403


def test_saving_credentials_does_not_prove_platform_or_merchant_connection(db, admin):
    credentials(db)
    result = items(admin[0])
    assert result['douyin_app']['state'] == 'unverified'
    assert result['orders_1']['state'] == 'unverified'
    assert 'fixture-app-secret' not in str(result)


def test_real_probe_validates_response_without_emitting_business_messages(db, engine, admin, order, monkeypatch):
    credentials(db)
    calls = []
    monkeypatch.setattr(engine.client, 'token', lambda **kwargs: 'fixture-access-token')
    def request(method, path, account, params=None, body=None):
        calls.append((method, account, params))
        return {'orders': [order]}
    monkeypatch.setattr(engine.client, 'request', request)
    client, headers = admin
    response = client.post('/api/connections/douyin/check', json={'enterprise_id': 1}, headers=headers)
    assert response.json['state'] == 'ready'
    assert response.json['metrics'] == {'sample_orders': 1, 'with_store': 1, 'with_phone': 0, 'with_package': 1}
    assert calls[0][0:2] == ('GET', '1001') and calls[0][2]['page_size'] == 5
    assert db.one('SELECT COUNT(*) AS n FROM messages')['n'] == 0
    assert db.one('SELECT sync_cursor FROM enterprises WHERE id=1')['sync_cursor'] is None
    result = items(client)
    assert result['douyin_app']['state'] == 'ready' and result['orders_1']['state'] == 'ready'
    assert result['orders_2']['state'] == 'unverified'


def test_missing_merchant_authorization_keeps_app_verified_and_explains_next_step(db, engine, admin, monkeypatch):
    credentials(db)
    monkeypatch.setattr(engine.client, 'token', lambda **kwargs: 'fixture-access-token')
    def denied(*args, **kwargs):
        raise PlatformError(2119005, '应用未获商家授权')
    monkeypatch.setattr(engine.client, 'request', denied)
    client, headers = admin
    response = client.post('/api/connections/douyin/check', json={'enterprise_id': 1}, headers=headers)
    assert response.json['state'] == 'failed' and '同意授权' in response.json['detail']
    assert items(client)['douyin_app']['state'] == 'ready'


def test_empty_success_is_distinguished_from_missing_order_array(db, engine, admin, monkeypatch):
    credentials(db)
    monkeypatch.setattr(engine.client, 'token', lambda **kwargs: 'fixture-access-token')
    monkeypatch.setattr(engine.client, 'request', lambda *a, **k: {'orders': []})
    client, headers = admin
    result = client.post('/api/connections/douyin/check', json={'enterprise_id': 1}, headers=headers).json
    assert result['state'] == 'ready' and '无订单' in result['detail']
    monkeypatch.setattr(engine.client, 'request', lambda *a, **k: {})
    result = client.post('/api/connections/douyin/check', json={'enterprise_id': 1}, headers=headers).json
    assert result['state'] == 'failed' and '缺少' in result['detail']


def test_changed_credentials_and_expired_checks_are_not_current_evidence(db):
    credentials(db)
    old = identity(db, '1001')
    save_check(db, 'orders_1', 'ready', 'fixture', old)
    db.set_secret('douyin_secret', 'replacement-fixture-secret')
    assert current_check(db, 'orders_1', identity(db, '1001'))['state'] == 'unverified'
    old = identity(db, '1001')
    save_check(db, 'orders_1', 'ready', 'fixture', old)
    check = db.settings('connection_check_orders_1')
    db.set_settings('connection_check_orders_1', {**check, 'checked_at': time.time() - 86401})
    assert current_check(db, 'orders_1', old)['state'] == 'unverified'


def test_external_ingest_does_not_claim_a_native_douyin_lead_connector(admin, db):
    client, headers = admin
    client.post('/api/manual/lead', json=lead(), headers=headers)
    assert items(client)['leads']['checked_at'] is None
    client.post('/api/ingest', json=lead('external'), headers={'Authorization': 'Bearer ' + db.secret('ingest_token')})
    result = items(client)['leads']
    assert result['checked_at'] and result['state'] == 'unconfigured'
    assert '核对上游来源' in result['detail']


def test_test_sender_scope_does_not_prove_real_store_coverage(admin, db):
    prepare_test_group(db)
    client, _ = admin
    client.post('/api/relay/heartbeat', json={'worker_id': 'test-only', 'ready': True, 'groups': [TEST_GROUP_ID]},
                headers={'Authorization': 'Bearer ' + db.secret('relay_token')})
    assert items(client)['sender']['state'] == 'partial'
    assert '0 / 2' in items(client)['sender']['detail']


def test_test_and_manual_receipts_do_not_prove_automatic_business_delivery(admin, engine, db):
    client, headers = admin
    prepared = prepare_test_group(db)
    result = client.post('/api/test-message', json={'store_id': prepared['store']['id']}, headers=headers).json
    engine.ingest_event(lead())
    with db.connect(write=True) as connection:
        connection.execute("UPDATE messages SET status='sent',result_source='manual',sent_at=?", (time.time(),))
        connection.execute("UPDATE messages SET result_source='sender' WHERE id=?", (result['message_id'],))
    delivery = items(client)['delivery']
    assert delivery['state'] == 'unverified' and '0 条正式' in delivery['detail'] and '1 条测试' in delivery['detail']


def test_formal_empty_instance_does_not_run_a_fake_successful_sync(tmp_path):
    app = create_app(tmp_path / 'formal', password=PASSWORD)
    client = app.test_client()
    headers = {'X-CSRF-Token': client.post('/api/login', json={'username': 'admin', 'password': PASSWORD}).json['csrf']}
    response = client.post('/api/tasks/run', json={}, headers=headers)
    assert response.status_code == 400 and '正式企业' in response.json['error']
    assert app.extensions['db'].one('SELECT COUNT(*) AS n FROM task_runs')['n'] == 0


def test_demo_cannot_call_real_upstream_or_claim_connection(tmp_path, monkeypatch):
    app = create_app(tmp_path / 'demo', password=PASSWORD, demo=True)
    def unexpected(*args, **kwargs):
        raise AssertionError('演示环境不能调用真实平台')
    monkeypatch.setattr(app.extensions['engine'].client, 'token', unexpected)
    client = app.test_client()
    headers = {'X-CSRF-Token': client.post('/api/login', json={'username': 'admin', 'password': PASSWORD}).json['csrf']}
    assert client.post('/api/connections/douyin/check', json={}, headers=headers).status_code == 409
    assert all(item['state'] == 'blocked' for item in items(client).values())

import json
import runpy
import sys
from pathlib import Path

import pytest

from toolbox.db import Database
from toolbox.testing import TEST_ACCOUNT_ID, TEST_GROUP_ID, TEST_GROUP_NAME, TEST_POI_ID
from .conftest import delivery, lead


def prepare(admin):
    client, headers = admin
    result = client.post('/api/test-group', json={}, headers=headers)
    assert result.status_code == 200
    return result.json['store']


def test_dedicated_group_configuration_is_idempotent_and_does_not_queue(admin, db):
    client, headers = admin
    assert client.get('/api/test-group').json['configured'] is False
    first, second = prepare(admin), prepare(admin)
    assert first['id'] == second['id']
    assert first['group_name'] == TEST_GROUP_NAME and first['group_id'] == TEST_GROUP_ID
    assert first['is_test'] == 1 and first['account_id'] == TEST_ACCOUNT_ID
    assert db.one('SELECT COUNT(*) AS n FROM messages')['n'] == 0
    assert db.settings('notifications')['delivery_enabled'] is False
    dashboard = client.get('/api/dashboard').json
    assert dashboard['enterprises'] == 2 and dashboard['stores'] == 2
    assert client.post('/api/test-group', json={}).status_code == 403


@pytest.mark.parametrize('category,identifier_label', [
    ('new_order', '订单编号：'), ('new_lead', '留资编号：'), ('status_change', '订单编号：')])
def test_three_test_notifications_are_marked_and_scoped(admin, db, engine, category, identifier_label):
    store = prepare(admin)
    engine.ingest_event(lead())
    client, headers = admin
    result = client.post('/api/test-message', json={'store_id': store['id'], 'category': category}, headers=headers)
    assert result.status_code == 201
    message = client.get('/api/messages/'+str(result.json['message_id'])).json
    assert message['is_test'] == 1 and message['group_name'] == TEST_GROUP_NAME
    assert message['category'] == category and message['body'].startswith('【发送链路测试｜模拟数据】')
    assert identifier_label+result.json['record_id'] in message['body']
    assert '测试客户（模拟）' in message['body'] and '联系电话：' not in message['body']
    listed = client.get('/api/messages').json['items']
    assert next(item for item in listed if item['id'] == message['id'])['is_test'] == 1
    delivery(db)
    job = engine.claim('test-worker', [TEST_GROUP_ID])
    assert job['id'] == message['id'] and job['is_test'] is True
    assert job['group_id'] == TEST_GROUP_ID and job['group_name'] == TEST_GROUP_NAME
    assert engine.claim('test-worker', [TEST_GROUP_ID]) is None
    assert db.one('SELECT status FROM messages WHERE group_id=?', ('g1',))['status'] == 'pending'


def test_test_enterprise_never_calls_order_api(admin, engine, db):
    prepare(admin)
    called = []
    class Client:
        def orders(self, account, *args):
            called.append(account)
            return iter(())
    engine.client = Client()
    assert engine.run_sync()['status'] == 'success'
    assert called == ['1001', '1002']
    assert db.one('SELECT sync_cursor FROM enterprises WHERE account_id=?', (TEST_ACCOUNT_ID,))['sync_cursor'] is None


@pytest.mark.parametrize('channel', ['ingest', 'manual'])
def test_real_business_events_cannot_enter_test_enterprise(admin, app, db, channel):
    prepare(admin)
    data = lead(account=TEST_ACCOUNT_ID, poi=TEST_POI_ID)
    data['is_test'] = True
    client, headers = admin
    if channel == 'ingest':
        response = app.test_client().post('/api/ingest', json=data,
                                         headers={'Authorization':'Bearer '+db.secret('ingest_token')})
    else:
        response = client.post('/api/manual/lead', json=data, headers=headers)
    assert response.status_code == 400 and '测试企业' in response.json['error']
    assert db.one('SELECT COUNT(*) AS n FROM messages')['n'] == 0


def test_real_orders_cannot_enter_test_enterprise(admin, engine, order, db):
    prepare(admin)
    order['merchant_info']['account_id'] = TEST_ACCOUNT_ID
    order['poi']['poi_id'] = TEST_POI_ID
    with pytest.raises(ValueError, match='测试企业'):
        engine.ingest_order(TEST_ACCOUNT_ID, order)
    assert db.one('SELECT COUNT(*) AS n FROM snapshots')['n'] == 0


def test_test_endpoint_cannot_target_business_group(admin, db):
    client, headers = admin
    response = client.post('/api/test-message', json={'store_id':1}, headers=headers)
    assert response.status_code == 400
    assert db.one('SELECT COUNT(*) AS n FROM messages')['n'] == 0


def test_malformed_test_category_returns_400_without_creating_jobs(admin, db):
    store = prepare(admin)
    client, headers = admin
    for category in ({}, None, 'unsupported'):
        response = client.post('/api/test-message', json={'store_id':store['id'], 'category':category}, headers=headers)
        assert response.status_code == 400
    assert db.one('SELECT COUNT(*) AS n FROM messages')['n'] == 0


def test_test_group_binding_collision_rolls_back(admin, db):
    with db.connect(write=True) as c:
        c.execute('UPDATE stores SET group_name=? WHERE id=1', (TEST_GROUP_NAME,))
    client, headers = admin
    response = client.post('/api/test-group', json={}, headers=headers)
    assert response.status_code == 400 and '其他门店' in response.json['error']
    assert db.one('SELECT id FROM enterprises WHERE account_id=?', (TEST_ACCOUNT_ID,)) is None


def test_old_database_adds_test_flag_without_reclassifying_business(db):
    with db.connect(write=True) as c:
        c.execute('ALTER TABLE enterprises DROP COLUMN is_test')
    reopened = Database(db.directory)
    assert reopened.rows('SELECT is_test FROM enterprises') == [{'is_test':0}, {'is_test':0}]
    assert reopened.one('SELECT COUNT(*) AS n FROM stores')['n'] == 2


def test_sender_test_only_flag_overrides_existing_group_scope(tmp_path, monkeypatch):
    import sender.worker
    observed = {}
    path = tmp_path/'sender-config.json'
    config = {'server':'http://127.0.0.1:8790', 'token':'fixture', 'group_ids':['g1','g2']}
    path.write_text(json.dumps(config), encoding='utf-8')
    class Worker:
        def __init__(self, value):
            observed.update(value)
            self.data = tmp_path/'sender-data'
        def run(self, once=False):
            observed['once'] = once
    monkeypatch.setattr(sender.worker, 'Worker', Worker)
    monkeypatch.setattr(sys, 'argv', ['sender.py','--config',str(path),'--test-only','--once'])
    runpy.run_path(str(Path(__file__).resolve().parents[1]/'sender.py'), run_name='__main__')
    assert observed['group_ids'] == [TEST_GROUP_ID] and observed['once'] is True
    assert json.loads(path.read_text(encoding='utf-8')) == config

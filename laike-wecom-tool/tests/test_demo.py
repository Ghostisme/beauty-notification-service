from toolbox.demo import seed
from toolbox.web import create_app


def test_offline_demo_cannot_deliver_to_connected_sender(tmp_path):
    app=create_app(tmp_path/'demo',password='Test-demo-20261012',demo=True)
    seed(app)
    db=app.extensions['db'];client=app.test_client()
    db.set_settings('notifications',{**db.settings('notifications'),'delivery_enabled':True})
    headers={'Authorization':'Bearer '+db.secret('relay_token')}
    client.post('/api/relay/heartbeat',json={'worker_id':'w','ready':True,'groups':['demo-group-1']},headers=headers)
    assert client.post('/api/relay/claim',json={'worker_id':'w'},headers=headers).json['job'] is None
    result=app.extensions['engine'].run_sync()
    assert result['orders']==2 and result['status']=='success'

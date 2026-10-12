import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from .conftest import delivery, lead


@pytest.fixture
def bridge():
    state = {"requests": [], "reply": {"status": "sent", "group_id": "g1", "message_id": "fixture-receipt"}}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append({'payload': payload, 'key': self.headers.get('Idempotency-Key')})
            body = json.dumps(state['reply']).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}', state
    server.shutdown();server.server_close();thread.join(2)


def test_real_http_bridge_receipt_and_idempotency_header(engine,db,bridge):
    address,state=bridge
    db.set_settings('channel',{**db.settings('channel'),'mode':'http','http_url':address})
    delivery(db);message=engine.ingest_event(lead())
    assert engine.dispatch_once()['status']=='sent'
    assert state['requests'][0]['payload']['group_id']=='g1'
    assert state['requests'][0]['key']==state['requests'][0]['payload']['idempotency_key']
    assert engine.message_detail(message['message_id'])['result_source']=='sender'


@pytest.mark.parametrize('reply,status',[({'ok':True},'uncertain'),({'status':'accepted'},'waiting_receipt'),({'status':'sent'},'uncertain'),({'status':'sent','group_id':'g2'},'uncertain'),({'status':'failed','message':'未发送'},'pending')])
def test_http_200_needs_explicit_group_receipt(engine,db,bridge,reply,status):
    address,state=bridge;state['reply']=reply
    db.set_settings('channel',{**db.settings('channel'),'mode':'http','http_url':address})
    delivery(db);engine.ingest_event(lead())
    assert engine.dispatch_once()['status']==status


def test_http_timeout_is_uncertain_not_retry(engine,db):
    db.set_settings('channel',{**db.settings('channel'),'mode':'http','http_url':'http://127.0.0.1:1'})
    delivery(db);engine.ingest_event(lead())
    def timeout(*a,**k):raise requests.Timeout('fixture timeout after submit')
    engine.http.post=timeout
    assert engine.dispatch_once()['status']=='uncertain'
    assert engine.claim('another-worker') is None

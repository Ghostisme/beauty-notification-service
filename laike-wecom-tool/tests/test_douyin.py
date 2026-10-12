import copy
import time

import pytest

from toolbox.douyin import DouyinClient, PlatformError
from toolbox.domain import epoch, money, normalize_order, public_phone, time_text


def test_official_cursor_structure_and_page_total(db):
    client=DouyinClient(db);calls=[]
    def request(method,path,account,params=None,body=None):
        calls.append(params)
        if len(calls)==1:
            return {'orders':[{'order_id':str(i)} for i in range(100)],'page':{'total':101},'search_after':{'CursorValue':['100','abc']}}
        return {'orders':[{'order_id':'100'}],'page':{'total':101}}
    client.request=request
    assert len(list(client.orders('1001',10,20)))==101
    assert calls[0]['cursor']=='0'
    assert calls[1]['cursor']=='100,abc' and calls[1]['page_num']==1


@pytest.mark.parametrize('body',[{'data':{'error_code':2119005,'description':'未获授权'}}, {'data':{},'extra':{'error_code':2190008}}])
def test_http_200_business_error_is_error(body):
    with pytest.raises(PlatformError):DouyinClient.unpack(body)


def test_repeated_pages_and_max_pages_fail_without_silent_truncation(db):
    client=DouyinClient(db)
    client.request=lambda *a,**k:{'orders':[{'order_id':str(i)} for i in range(100)],'has_more':True,'search_after':{'CursorValue':['next']}}
    with pytest.raises(RuntimeError,match='重复'):list(client.orders('1001',1,2))
    with pytest.raises(RuntimeError,match='上限'):list(client.orders('1001',1,2,max_pages=1))


def test_real_empty_time_window_response_is_an_empty_order_page(db):
    client=DouyinClient(db)
    client.request=lambda *a,**k:{'error_code':0,'description':''}
    assert list(client.orders('1001',10,20))==[]


@pytest.mark.parametrize('data',[
    {},
    {'error_code':0,'orders':None},
    {'error_code':0,'orders':'not-an-array'},
    {'error_code':0,'unexpected_orders':[]},
    {'error_code':0,'page':{'total':3}},
    {'error_code':0,'search_after':{'CursorValue':['next']}},
])
def test_missing_or_malformed_orders_are_not_mistaken_for_explicit_empty_success(data):
    with pytest.raises(RuntimeError,match='缺少'):
        DouyinClient.order_items(data)


def test_expired_token_refreshes_once_and_merchant_header(db, monkeypatch):
    db.set_settings('douyin',{**db.settings('douyin'),'client_key':'fixture'})
    db.set_secret('douyin_secret','fixture-secret')
    class Response:
        def __init__(self,data):self.data=data
        def raise_for_status(self):pass
        def json(self):return self.data
    class Session:
        def __init__(self):self.tokens=0;self.calls=[]
        def post(self,*a,**k):
            self.tokens+=1;return Response({'data':{'access_token':f't{self.tokens}','expires_in':7200}})
        def request(self,*a,**k):
            self.calls.append(k)
            return Response({'data':{'error_code':2190008}} if len(self.calls)==1 else {'data':{'orders':[]}})
    session=Session();client=DouyinClient(db,session)
    assert client.request('GET','/test','1001')['orders']==[]
    assert session.tokens==2
    assert [c['headers']['access-token'] for c in session.calls]==['t1','t2']
    assert session.calls[1]['headers']['Rpc-Transit-Life-Account']=='1001'


def test_official_batch_decrypt_no_local_ciphertext_fallback(db, order):
    db.set_settings('douyin',{**db.settings('douyin'),'decrypt_enabled':True})
    client=DouyinClient(db)
    client.request=lambda *a,**k:{'results':[{'cipher_text':'Enc.not-a-phone','plain_text':'13800000000','is_success':True}]}
    records,warning=client.decrypt_orders([order],'1001')
    assert normalize_order(records[0])['phone']=='13800000000' and not warning
    assert order['contacts'][0]['phone_encrypt']=='Enc.not-a-phone'
    client._decrypt_cache.clear()
    def fail(*args,**kwargs):raise PlatformError(2119005,'未授权')
    client.request=fail
    records,warning=client.decrypt_orders([order],'1001')
    assert normalize_order(records[0])['phone']=='' and '未授权' in warning


def test_money_and_china_timezone_independent_of_server_timezone():
    assert money(10001)=='¥100.01'
    assert money('nan')==''
    assert time_text('2026-10-12T00:00:00Z')=='2026-10-12 08:00:00'
    assert epoch('2026-10-12 08:00:00')==epoch('2026-10-12T00:00:00Z')
    assert public_phone('138****0000')=='138****0000' and public_phone('Enc.13800000000')==''

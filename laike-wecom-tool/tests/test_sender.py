import copy

import pytest
import requests

from sender.desktop import BeforeSendError, UncertainSendError, WindowsDesktop, confirmation_anchors, exact_group, has_confirmation, profile_problem
from sender.worker import Worker


class Desktop:
    def __init__(self,fail=None):self.calls=0;self.fail=fail
    def ready(self):return True,'test desktop'
    def send(self,job,before):
        self.calls+=1
        if self.fail=='before':raise BeforeSendError('未点击发送')
        before()
        if self.fail=='after':raise UncertainSendError('点击发送后未收到确认')
        return {'status':'sent','group_id':job['group_id'],'detail':'模拟确认'}


@pytest.fixture
def job():
    return {'id':1,'idempotency_key':'laike-message-1-r0','lease_token':'lease1','group_id':'g1','group_name':'测试群','text':'【抖音来客｜新订单通知】\n订单编号：T1'}


def worker(tmp_path,desktop):
    value=Worker({'server':'http://127.0.0.1:1','token':'fixture','data_dir':str(tmp_path)},desktop)
    value.request=lambda *a,**k:{'status':'sent'}
    return value


def test_lost_receipt_does_not_resend_and_new_lease_can_ack(tmp_path,job):
    desktop=Desktop();w=worker(tmp_path,desktop)
    def disconnected(*a,**k):raise requests.ConnectionError('test disconnect')
    w.request=disconnected
    with pytest.raises(requests.ConnectionError):w.process(job)
    assert w.ledger.get(job['idempotency_key'])['state']=='sent'
    w.request=lambda *a,**k:{'status':'sent'}
    job['lease_token']='lease2'
    assert w.process(job)['status']=='sent' and desktop.calls==1
    assert not w.ledger.pending()


def test_uncertain_never_resends_without_explicit_manual_generation(tmp_path,job):
    desktop=Desktop('after');w=worker(tmp_path,desktop)
    assert w.process(job)['status']=='uncertain'
    assert w.process(job)['status']=='uncertain' and desktop.calls==1
    desktop.fail=None
    job['idempotency_key']='laike-message-1-r1'
    assert w.process(job)['status']=='sent' and desktop.calls==2


def test_explicit_before_send_failure_can_retry_same_key(tmp_path,job):
    desktop=Desktop('before');w=worker(tmp_path,desktop)
    assert w.process(job)['status']=='failed'
    desktop.fail=None
    assert w.process(job)['status']=='sent' and desktop.calls==2


def test_wrong_group_same_key_is_not_sent_again(tmp_path,job):
    desktop=Desktop();w=worker(tmp_path,desktop)
    w.process(job);job['group_id']='g2'
    assert w.process(job)['status']=='uncertain' and desktop.calls==1


def test_group_and_receipt_matching_requires_exact_identifiers():
    group='玥笙-辽宁-大连中山店'
    assert exact_group(group+' (12)',group,title=True)
    assert not exact_group(group+'旗舰',group,title=True)
    body='【抖音来客｜新订单通知】\n下单时间：2026-10-12 10:00:00\n订单编号：T-1001'
    anchors=confirmation_anchors(body)
    assert has_confirmation(body,anchors)
    assert not has_confirmation(body.replace('1001','1002'),anchors)
    with pytest.raises(BeforeSendError):confirmation_anchors('没有业务编号的消息')


@pytest.fixture
def profile():
    return {'window_size':[1000,700], 'search_point':[160,38], 'results_rect':[60,60,310,500],
            'header_rect':[310,0,1000,80], 'messages_rect':[310,80,1000,500], 'input_point':[500,600]}


def test_adjacent_calibration_regions_are_allowed_and_partial_selection_can_be_checked(profile):
    assert not profile_problem(profile)
    profile['results_rect']=[75,55,475,250]  # 企微搜索弹层可以覆盖右侧聊天区。
    assert not profile_problem(profile)
    partial={k:v for k,v in profile.items() if k in ('window_size','search_point','results_rect')}
    assert not profile_problem(partial,complete=False)
    assert profile_problem(partial)


@pytest.mark.parametrize('change',[
    {'header_rect':[310,0,1000,700]},
    {'header_rect':[0,0,1000,80]},
    {'input_point':[500,400]},
    {'messages_rect':[310,80,1200,500]},
    {'search_point':[float('nan'),38]},
])
def test_unsafe_calibration_is_rejected(profile,change):
    profile.update(change)
    assert profile_problem(profile)


def test_title_crop_including_chat_content_stops_before_any_send_action(profile,job):
    profile['header_rect']=[310,0,1000,700]
    desktop=WindowsDesktop.__new__(WindowsDesktop)
    desktop.profile=profile
    desktop.unlocked=lambda:True
    desktop.find_window=lambda:1
    submitted=[]
    with pytest.raises(BeforeSendError,match='重叠'):
        desktop.send(job,lambda:submitted.append(True))
    assert submitted==[]


@pytest.mark.parametrize('matching', [True, False])
def test_test_group_name_scope_works_for_real_merchant_and_never_expands_when_missing(tmp_path, matching):
    from toolbox.testing import TEST_GROUP_NAME
    w=Worker({'server':'http://127.0.0.1:1','token':'fixture','data_dir':str(tmp_path),
              'group_names':[TEST_GROUP_NAME]}, Desktop())
    sent=[]
    def request(path, body=None):
        if path.endswith('/groups'):
            groups=[{'group_id':'business-group-1','group_name':'其他门店群'}]
            if matching:groups.append({'group_id':'real-test-store-group','group_name':TEST_GROUP_NAME})
            return {'items':groups}
        sent.append(body);return {'ok':True}
    w.request=request
    assert w.heartbeat() is matching
    assert sent[0]['groups'] == (['real-test-store-group'] if matching else [])
    assert sent[0]['ready'] is matching
    assert w.desktop.calls==0


def test_missing_test_group_does_not_call_claim(tmp_path):
    from toolbox.testing import TEST_GROUP_NAME
    w=Worker({'server':'http://127.0.0.1:1','token':'fixture','data_dir':str(tmp_path),
              'group_names':[TEST_GROUP_NAME]}, Desktop())
    calls=[]
    def request(path, body=None):
        calls.append(path)
        return {'items':[{'group_id':'other','group_name':'其他门店群'}]} if path.endswith('/groups') else {'ok':True}
    w.request=request;w.run(once=True)
    assert '/api/relay/claim' not in calls and w.desktop.calls==0

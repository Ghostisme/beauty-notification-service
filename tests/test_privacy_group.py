# -*- coding: utf-8 -*-
"""敏感信息提醒：判定依据必须是【目标群名称】，不是消息内容，也不动 push.fields。

运行: python tests/test_privacy_group.py
"""
import contextlib
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage

tmp = os.path.join(tempfile.gettempdir(), "privacy_test.db")
if os.path.exists(tmp):
    os.remove(tmp)
storage.DB_PATH = tmp
storage.init()

import sync


def capture(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ---------- 纯函数: 只看群名 ----------
assert sync.matched_keywords("超英客户服务群") == ["客户服务群"], sync.matched_keywords("超英客户服务群")
assert sync.matched_keywords("余乐圈客户群") == ["客户群"]
assert sync.is_multi_customer_group("超英门店工作群") is False
assert sync.is_multi_customer_group("") is False
assert sync.is_multi_customer_group(None) is False
assert sync.is_multi_customer_group("超英客户服务群", []) is False, "显式传 [] 必须彻底关掉"
assert sync.matched_keywords("余乐圈VIP福利群", ["福利"]) == ["福利"]
assert sync.matched_keywords("余乐圈VIP福利群", ["vip"]) == ["vip"], "关键词匹配要忽略大小写"

# ---------- 真实群名规则(品牌-省-市门店店) + 通配符 ----------
REAL = "玥笙-辽宁-大连中山店"
GEN = ["玥笙-*", "客户群", "会员群"]

assert sync.matched_keywords(REAL, GEN) == ["玥笙-*"], sync.matched_keywords(REAL, GEN)
assert sync.is_multi_customer_group(REAL, GEN) is True
# 每家门店 / 每个城市都覆盖, 新开门店不用改配置
for g in ["玥笙-广东-深圳福田店", "玥笙-辽宁-沈阳中街店", "玥笙-浙江-杭州西湖店"]:
    assert sync.is_multi_customer_group(g, GEN) is True, g
# 测试群、内部群不该被命中(否则测试时也弹提醒, 干扰判断)
assert sync.is_multi_customer_group("抖音本地生活订单通知", GEN) is False
assert sync.is_multi_customer_group("玥笙门店内部工作群", GEN) is False, "少了连字符就不是门店群形状"
# 通用词对「玥笙-辽宁-大连中山店」这类群名命中不了 —— 所以本项目干脆关掉提醒(keywords=[])
assert sync.is_multi_customer_group(REAL, sync.DEFAULT_MULTI_CUSTOMER_KEYWORDS) is False
# * = 任意多个字符, ? = 正好一个字符
assert sync.matched_keywords(REAL, ["玥笙-??-大连中山店"]) == ["玥笙-??-大连中山店"]
assert sync.matched_keywords(REAL, ["玥笙-?-大连中山店"]) == [], "辽宁是两个字, 一个 ? 匹配不上"
assert sync.matched_keywords(REAL, ["*中山*"]) == ["*中山*"]
# 通配符里的正则元字符必须当字面量, 不能被当正则元字符乱匹配
assert sync.matched_keywords("玥笙3辽宁大连店", ["玥笙.辽宁"]) == []
assert sync.matched_keywords("玥笙.辽宁-大连店", ["玥笙.辽宁"]) == ["玥笙.辽宁"]

# ---------- 默认值填充: 没写=用默认, 显式写 [] = 关掉 ----------
filled = sync.wecom_with_privacy_defaults({})
assert filled["privacy_multi_customer_keywords"] == sync.DEFAULT_MULTI_CUSTOMER_KEYWORDS
assert filled["privacy_warn_fields"] == ["phone"]
assert sync.wecom_with_privacy_defaults({"privacy_multi_customer_keywords": []})["privacy_multi_customer_keywords"] == []

# ---------- 端到端: 入队前的提醒条件 ----------
WITH_PHONE = [{"msgtype": "markdown", "markdown": {"content": "订单已支付\n手机号 13812345678"}}]
NO_PHONE = [{"msgtype": "markdown", "markdown": {"content": "订单已支付\n金额 199"}}]

# ① 多客户群 + 内容里有手机号 → 提醒
out = capture(sync.send_to_outbox, WITH_PHONE, {"wechat_group": "超英客户服务群"}, {}, True)
assert "多客户群" in out, out

# ② 多客户群但没有手机号 → 静默(提醒是"内容里有号码"才提, 不是见群就念)
out = capture(sync.send_to_outbox, NO_PHONE, {"wechat_group": "超英客户服务群"}, {}, True)
assert "多客户群" not in out, out

# ③ 群名不是多客户群类型(门店内部群) → 即使有手机号也不打扰
out = capture(sync.send_to_outbox, WITH_PHONE, {"wechat_group": "超英门店工作群"}, {}, True)
assert "多客户群" not in out, out

# ④ 关键词显式置空 → 永不提醒
out = capture(sync.send_to_outbox, WITH_PHONE,
              {"wechat_group": "超英客户服务群", "privacy_multi_customer_keywords": []}, {}, True)
assert "多客户群" not in out, out

# ⑤ 自定义关键词生效
out = capture(sync.send_to_outbox, WITH_PHONE,
              {"wechat_group": "余乐圈VIP福利群", "privacy_multi_customer_keywords": ["福利"]}, {}, True)
assert "多客户群" in out, out

# ⑥ 提醒绝不动内容: 手机号原样留在待发文案里
assert "13812345678" in sync.md_to_text(WITH_PHONE[0]["markdown"]["content"])

# ⑦ 手机号检测本身(11 位大陆号; 10 位/前后粘数字不算)
assert sync.phone_in_text("13812345678") is True
assert sync.phone_in_text("1381234567") is False
assert sync.phone_in_text("") is False

# ---------- push.fields 是手机号的唯一开关(卡片模板 / 汇总 / 每单一条都适用) ----------
ORDER = [{"order_id": "A1", "goods": "小气泡清洁", "amount": "199", "status": "已支付待核销",
          "customer": "张女士", "phone": "13812345678",
          "created_at": "2026-09-20 12:00:00", "shop": "超英皮肤定制"}]


def render(fields, template="order", per_order=False):
    msgs = sync.build_messages(ORDER, {"template": template, "per_order": per_order, "fields": fields})
    return sync.md_to_text(msgs[0]["markdown"]["content"])


assert "13812345678" in render(["order_id", "goods", "amount", "customer", "phone"]), "fields 里有 phone 就该展示"
assert "13812345678" not in render(["order_id", "goods", "amount", "customer"]), "fields 里没有 phone 就不该出现"
assert "13812345678" in render(["phone"], template="lead"), "lead 模板同样受 fields 控制"
assert "13812345678" not in render(["customer"], template="lead")
assert "13812345678" in render(["order_id", "phone"], per_order=True), "每单一条的模式同样受 fields 控制"
# 解不出号码时不留一行 "-"
assert "联系电话" not in render(["order_id", "phone"]) .replace("联系电话：13812345678", ""), "空号码不该产生占位行"
no_phone = sync.build_messages([{**ORDER[0], "phone": ""}],
                               {"template": "order", "per_order": False, "fields": ["phone"]})
assert "联系电话" not in sync.md_to_text(no_phone[0]["markdown"]["content"]), "没有号码就整行不出现"

print("--- 隐私提醒(按群名称) 全部断言通过 ---")
os.remove(tmp)

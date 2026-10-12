from copy import deepcopy

ORDER_TEMPLATE = """【抖音来客｜新订单通知】
门店：{门店名称}
客户：{客户称呼}
联系电话：{客户手机号}
团购项目：{团购卡／套餐名称}
购买数量：{数量}
实付金额：{金额}
订单状态：{状态}
下单时间：{下单时间}
订单编号：{订单编号}"""

LEAD_TEMPLATE = """【抖音来客｜新留资通知】
门店：{门店名称}
客户：{客户称呼}
联系电话：{客户手机号}
意向项目：{意向项目}
留资来源：{留资来源}
留资时间：{留资时间}
客户备注：{备注}
留资编号：{留资编号}"""

STATUS_TEMPLATE = """【抖音来客｜{状态变化名称}】
门店：{门店名称}
客户：{客户称呼}
联系电话：{客户手机号}
团购项目：{团购卡／套餐名称}
购买数量：{数量}
实付金额：{金额}
状态变化：{原状态} → {当前状态}
变化时间：{变化时间}
订单编号：{订单编号}"""

TEMPLATES = {
    "new_order": {"name": "新订单通知", "enabled": True, "body": ORDER_TEMPLATE, "missing": "omit"},
    "new_lead": {"name": "新留资通知", "enabled": True, "body": LEAD_TEMPLATE, "missing": "omit"},
    "status_change": {"name": "状态变化通知", "enabled": True, "body": STATUS_TEMPLATE, "missing": "omit"},
}

VARIABLES = ["门店名称", "企业名称", "客户称呼", "客户手机号", "团购卡／套餐名称", "数量", "金额",
             "状态", "下单时间", "订单编号", "意向项目", "留资来源", "留资时间", "备注", "留资编号",
             "状态变化名称", "原状态", "当前状态", "变化时间", "退款金额", "核销编号"]

SETTINGS = {
    "scheduler": {"enabled": False, "interval_seconds": 120, "lookback_minutes": 30,
                  "max_age_minutes": 180, "max_pages": 50, "history_days": 90},
    "notifications": {"delivery_enabled": False, "order_trigger": "paid",
                      "status_events": ["verified", "refunded", "canceled"],
                      "verified_statuses": [401], "refunded_statuses": [301], "refunding_statuses": [300]},
    "douyin": {"base_url": "https://open.douyin.com", "client_key": "",
               "order_path": "/goodlife/v1/trade/order/query/", "decrypt_enabled": False,
               "decrypt_path": "/goodlife/v1/open/common_biz/crypto/decrypt/batch", "amount_unit": "fen"},
    "channel": {"mode": "relay", "http_url": "", "timeout_seconds": 20,
                "interval_seconds": 3, "max_attempts": 5, "lease_seconds": 180},
}

STATUS_LABELS = {"pending": "待发送", "sending": "发送中", "waiting_receipt": "等待回执",
                 "sent": "已发送", "failed": "发送失败", "uncertain": "待人工核实",
                 "unrouted": "待分配门店", "blocked": "门店或企业已暂停", "muted": "通知已关闭",
                 "skipped_old": "历史记录", "canceled": "已取消"}

ORDER_STATUSES = {"0": "初始化", "100": "待支付", "101": "支付取消", "200": "已支付",
                  "201": "待使用", "1": "已完成", "150": "部分支付"}

EVENT_NAMES = {"paid": "支付成功通知", "verified": "核销成功通知", "refunding": "退款申请通知",
               "refunded": "退款成功通知", "canceled": "订单取消通知"}


def fresh_settings():
    return deepcopy(SETTINGS)

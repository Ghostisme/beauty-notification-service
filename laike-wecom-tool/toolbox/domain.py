import datetime as dt
import hashlib
import json
import re
import string
import time
from decimal import Decimal, InvalidOperation

from .defaults import ORDER_STATUSES, VARIABLES

SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def epoch(value, fallback=None):
    if value in (None, "", 0, "0"):
        return fallback
    try:
        n = float(value)
        if n > 1e11:
            n /= 1000
        if not 0 < n < 4102444800:
            return fallback
        return n
    except (ValueError, TypeError):
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=SHANGHAI)
            return parsed.timestamp()
        except ValueError:
            return fallback


def time_text(value):
    n = epoch(value)
    return dt.datetime.fromtimestamp(n, SHANGHAI).strftime("%Y-%m-%d %H:%M:%S") if n else ""


def text(value, limit=500):
    return str(value if value is not None else "").strip()[:limit]


def money(value, unit="fen"):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or abs(amount) > Decimal("100000000000"):
            return ""
        if unit == "fen":
            amount /= 100
        return f"¥{amount:.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return ""


def public_phone(value):
    value = text(value, 100)
    if value.startswith("Enc.") or not re.fullmatch(r"[+\d*\s()\-]{5,35}", value):
        return ""
    return value


def normalize_order(raw, amount_unit="fen"):
    if not isinstance(raw, dict):
        raise ValueError("订单必须是对象")
    record_id = text(raw.get("order_id"), 120)
    if not record_id:
        raise ValueError("订单缺少 order_id")
    poi = raw.get("poi") if isinstance(raw.get("poi"), dict) else {}
    buyer = raw.get("buyer_info") if isinstance(raw.get("buyer_info"), dict) else {}
    contacts = raw.get("contacts") if isinstance(raw.get("contacts"), list) else []
    contact = next((v for v in contacts if isinstance(v, dict)), {})
    products = raw.get("products") or []
    if not isinstance(products, list):
        products = []
    names = [text(p.get("product_name") or (p.get("snapshot_product") or {}).get("product_name") or p.get("sku_name"), 200)
             for p in products if isinstance(p, dict) and isinstance(p.get("snapshot_product", {}), dict)]
    quantity = raw.get("count") or raw.get("quantity")
    if quantity is None:
        quantities = [p.get("count") or p.get("quantity") for p in products if isinstance(p, dict)]
        quantity = sum(int(v) for v in quantities if str(v).isdigit()) or None
    phone = next((public_phone(v) for v in (buyer.get("buyer_real_phone"), contact.get("phone"),
                 contact.get("phone_encrypt"), buyer.get("buyer_phone"), raw.get("phone")) if public_phone(v)), "")
    customer = contact.get("name") or buyer.get("name") or raw.get("customer") or ""
    if str(customer).startswith("Enc."):
        customer = ""
    status = text(raw.get("order_status"), 50)
    certs = {}
    for item in raw.get("certificate") or raw.get("certificates") or []:
        if not isinstance(item, dict):
            continue
        identifier = text(item.get("certificate_id") or item.get("order_item_id"), 120)
        if identifier:
            certs[identifier] = {"status": text(item.get("item_status"), 50),
                                 "time": epoch(item.get("item_update_time") or item.get("refund_time")),
                                 "refund_amount": money(item.get("refund_amount"), amount_unit),
                                 "poi_id": text(item.get("poi_id") or item.get("verify_poi_id"), 120)}
    return {"record_id": record_id, "poi_id": text(poi.get("poi_id") or raw.get("poi_id") or raw.get("intention_poi_id"), 120),
            "poi_name": text(poi.get("poi_name") or raw.get("poi_name")), "customer": text(customer), "phone": phone,
            "goods": "、".join(v for v in names if v) or text(raw.get("sku_name") or raw.get("product_name") or raw.get("goods")),
            "quantity": text(quantity, 30), "amount": money(raw.get("pay_amount", raw.get("amount")), amount_unit),
            "status_code": status, "status": ORDER_STATUSES.get(status, status), "certificates": certs,
            "created_time": epoch(raw.get("create_order_time") or raw.get("created_at")),
            "paid_time": epoch(raw.get("pay_time") or raw.get("pay_order_time")),
            "updated_time": epoch(raw.get("update_order_time") or raw.get("updated_at")),
            "phone_available": bool(phone)}


def event_key(account_id, category, record_id, identity=""):
    return hashlib.sha256(json.dumps([str(account_id), category, str(record_id), str(identity)], ensure_ascii=False).encode()).hexdigest()


def validate_template(body):
    if not isinstance(body, str) or not body.strip() or len(body) > 12000:
        raise ValueError("模板不能为空，且不能超过 12000 个字符")
    try:
        for _, field, fmt, conv in string.Formatter().parse(body):
            if field is not None and (field not in VARIABLES or fmt or conv):
                raise ValueError(f"不支持的模板变量：{field}")
    except (ValueError, KeyError) as e:
        raise ValueError(f"模板格式错误：{e}") from e
    return body.strip()


def variables(payload, enterprise_name="", store_name=""):
    return {"门店名称": store_name or payload.get("poi_name", ""), "企业名称": enterprise_name,
            "客户称呼": payload.get("customer", ""), "客户手机号": payload.get("phone", ""),
            "团购卡／套餐名称": payload.get("goods", ""), "数量": payload.get("quantity", ""),
            "金额": payload.get("amount", ""), "状态": payload.get("status", ""),
            "下单时间": time_text(payload.get("created_time")), "订单编号": payload.get("record_id", ""),
            "意向项目": payload.get("intent", ""), "留资来源": payload.get("source", ""),
            "留资时间": time_text(payload.get("event_time")), "备注": payload.get("remark", ""),
            "留资编号": payload.get("record_id", ""), "状态变化名称": payload.get("event_name", ""),
            "原状态": payload.get("previous_status", ""), "当前状态": payload.get("current_status", ""),
            "变化时间": time_text(payload.get("event_time")), "退款金额": payload.get("refund_amount", ""),
            "核销编号": payload.get("certificate_id", "")}


def render(template, payload, enterprise_name="", store_name=""):
    values = variables(payload, enterprise_name, store_name)
    lines = []
    for line in template["body"].splitlines():
        fields = [field for _, field, _, _ in string.Formatter().parse(line) if field]
        if template.get("missing") == "omit" and fields and any(values.get(f) in (None, "") for f in fields):
            continue
        lines.append(line.format_map({k: str(v) if v not in (None, "") else "未提供" for k, v in values.items()}))
    result = "\n".join(lines).strip()
    if len(result.encode("utf-8")) > 16000:
        raise ValueError("生成的消息超过 16000 字节，请缩短模板")
    return result


def error_text(error, sensitive=()):
    result = str(error)
    for value in sensitive:
        if value:
            result = result.replace(str(value), "[已隐藏]")
    result = re.sub(r"(?i)(access[_-]?token|secret|password|token|key)=([^\s&]+)", r"\1=[已隐藏]", result)
    return result[:1500]

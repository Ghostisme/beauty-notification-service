# -*- coding: utf-8 -*-
"""
抖音来客订单 -> 企业微信群 同步脚本

用法:
  python sync.py                     # 按 config.json 的 mode 执行
  python sync.py --file orders.csv   # 指定订单文件(CSV/Excel导出)推送
  python sync.py --dry-run           # 只打印消息内容, 不真正发送(用于测试)
  python sync.py --api               # 强制走 API 模式(逐商户拉单)
  python sync.py --serve             # 常驻服务模式(服务器部署): 定时拉单+监听导出文件目录
  python sync.py --list-groups       # 列出企业微信客户群(获取 chat_id 用于配置)
  python sync.py --merchant 门店A     # 多商户时指定商户(按 name 或序号, 默认第一个)

数据来源二选一:
  1) file 模式: 从抖音来客后台导出订单表格(CSV/Excel), 支持中文列名自动识别
  2) api  模式: 服务商模式, 用 client_token + account_id 逐商户拉单
     (订单接口 /goodlife/v1/akte/order/query/, 参数以官方文档为准)

服务商模式说明:
  - 商家在抖音来客「店铺管理 -> 第三方应用授权」授权服务商应用后,
    服务商用 client_token + 来客商户根账户ID(account_id) 代调用接口,
    多个商户在 config.json 的 merchants 列表中各配一条。
  - 订单中的客户手机号为 AES 加密密文, 脚本默认本地解密
    (key=clientSecret 补齐/裁剪至32字节, IV=key前16字节, AES-256-CBC),
    也可配置 douyin.phone_decrypt 走官方批量解密接口。

推送目标:
  - 内部群: 走群机器人 Webhook(简单可靠)
  - 外部客户群(含微信用户): 群机器人不支持, 走「客户联系-企业群发」API,
    群主需在手机端「群发助手」确认后消息才会发出,
    且每个客户群每天默认只能接收 1 条群发(可在群发助手调整规则)
"""

import argparse
import base64
import csv
import datetime as dt
import json
import os
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

OPEN_DOUYIN_BASE = "https://open.douyin.com"
WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"

# 订单查询接口(服务商模式), 参数以官方文档为准
ORDER_QUERY_PATH = "/goodlife/v1/akte/order/query/"
# 官方批量解密接口(本地解密失败时的回退)
DECRYPT_BATCH_PATH = "/goodlife/v1/open/common_biz/crypto/decrypt/batch/"

# 中文列名 -> 内部字段 的常见映射(导出表格列名可能略有差异, 可自行补充)
COLUMN_ALIASES = {
    "order_id": ["订单号", "订单ID", "订单编号", "order_id", "order no", "order_no", "order id"],
    "goods": ["商品名称", "商品", "套餐名称", "商品标题", "goods", "product", "title"],
    "amount": ["实付金额", "支付金额", "订单金额", "金额", "amount", "price", "total_amount"],
    "status": ["订单状态", "状态", "status", "order_status"],
    "customer": ["客户名称", "顾客姓名", "联系人", "买家昵称", "customer", "buyer", "nick_name"],
    "phone": ["手机号", "联系电话", "电话", "客户手机号", "phone", "mobile", "telephone"],
    "created_at": ["下单时间", "订单时间", "创建时间", "支付时间", "created_at", "create_time", "order time"],
    "shop": ["门店名称", "门店", "店铺名称", "shop", "store"],
}
STATUS_EMOJI = {
    "待支付": "⏳", "待核销": "🎟️", "已支付": "✅", "已核销": "🎟️",
    "已完成": "🏁", "已取消": "❌", "退款中": "↩️", "已退款": "↩️", "待发货": "📦",
}
# 订单接口返回中, 加密手机号可能出现的字段名(含嵌套, 递归查找)
PHONE_ENCRYPT_KEYS = ("encrypt_phone", "encrypted_phone", "enc_phone",
                      "encrypt_mobile", "encrypted_mobile", "phone_encrypt",
                      "encrypt_contact_phone", "enc_telephone")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------- 商户模型 ----------------

def normalize_merchants(cfg):
    """把 config 归一化成商户列表。
    新配置: merchants 列表, 每项含 account_id/name/push/wecom。
    旧配置(无 merchants): 兼容为单商户, account_id 取 douyin.account_id。
    """
    dy = cfg.get("douyin", {})
    default_push = cfg.get("push", {})
    default_wecom = cfg.get("wecom", {})
    merchants = []
    if cfg.get("merchants"):
        for i, m in enumerate(cfg["merchants"]):
            merchants.append({
                "account_id": str(m.get("account_id", "")).strip(),
                "name": m.get("name") or f"商户{i + 1}",
                "push": {**default_push, **(m.get("push") or {})},
                "wecom": {**default_wecom, **(m.get("wecom") or {})},
            })
    else:
        merchants.append({
            "account_id": str(dy.get("account_id", "")).strip(),
            "name": dy.get("account_name") or "默认商户",
            "push": default_push,
            "wecom": default_wecom,
        })
    return merchants


def pick_merchant(merchants, spec):
    """按 name 或 1-based 序号选择商户。"""
    if not spec:
        return merchants[0]
    if str(spec).isdigit():
        idx = int(spec) - 1
        if 0 <= idx < len(merchants):
            return merchants[idx]
        sys.exit(f"商户序号 {spec} 超出范围, 当前共 {len(merchants)} 个商户。")
    for m in merchants:
        if m["name"] == spec:
            return m
    sys.exit(f"找不到名为「{spec}」的商户, 可选: {', '.join(m['name'] for m in merchants)}")


# ---------------- 文件模式 ----------------

def normalize_columns(rows):
    """把各种可能的列名归一化成内部字段名。"""
    out = []
    for row in rows:
        item = {}
        for key, value in row.items():
            k = (key or "").strip().lower()
            matched = None
            for field, aliases in COLUMN_ALIASES.items():
                if k in (a.lower() for a in aliases):
                    matched = field
                    break
            item[matched or key.strip()] = (value or "").strip() if isinstance(value, str) else value
        out.append(item)
    return out


def read_orders_file(path):
    """读取 CSV 或 Excel(xlsx) 订单导出文件, 返回 dict 列表。"""
    ext = os.path.splitext(path)[1].lower()
    rows = []
    if ext in (".xlsx", ".xls"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            sys.exit("读取 Excel 需要安装 openpyxl: python -m pip install openpyxl\n"
                     "或者把订单导出为 CSV 后重试。")
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header = None
        for r in rows_iter:
            if header is None:
                header = [str(c).strip() if c is not None else "" for c in r]
                continue
            if not any(c is not None and str(c).strip() for c in r):
                continue
            rows.append(dict(zip(header, ["" if c is None else str(c).strip() for c in r])))
    else:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(f, dialect=dialect)
            rows = [dict(r) for r in reader]
    return normalize_columns(rows)


# ---------------- API 模式(服务商: client_token + account_id) ----------------

def get_douyin_credentials(cfg):
    """凭证优先级: 环境变量 DOUYIN_CLIENT_KEY/SECRET > config.json。"""
    d = cfg["douyin"]
    key = os.environ.get("DOUYIN_CLIENT_KEY") or d.get("client_key", "")
    secret = os.environ.get("DOUYIN_CLIENT_SECRET") or d.get("client_secret", "")
    if "在此填入" in (key + secret):
        sys.exit("尚未配置来客开放平台凭证, 请编辑 config.json 的 douyin 部分(或设置环境变量)。")
    return key, secret


_token_cache = {"token": None, "expire_at": 0}


def get_client_token(cfg, force=False):
    """服务商应用 client_token(client_credential), 带内存缓存。"""
    if not force and _token_cache["token"] and time.time() < _token_cache["expire_at"]:
        return _token_cache["token"]
    key, secret = get_douyin_credentials(cfg)
    resp = requests.post(cfg["douyin"].get("token_url", OPEN_DOUYIN_BASE + "/oauth/client_token"), json={
        "client_key": key,
        "client_secret": secret,
        "grant_type": "client_credential",
    }, timeout=15)
    data = resp.json().get("data", {})
    token = data.get("access_token")
    if not token:
        sys.exit(f"获取 client_token 失败: {resp.text}")
    _token_cache["token"] = token
    _token_cache["expire_at"] = time.time() + int(data.get("expires_in", 7200)) - 300
    return token


def _resp_items(data):
    return data.get("order_list") or data.get("orders") or data.get("list") or []


def _is_token_error(msg):
    m = str(msg).lower()
    return any(k in m for k in ("token", "失效", "过期", "invalid", "expired"))


def fetch_orders_api(cfg, merchant, token, lookback_minutes=None):
    """调来客订单查询接口, 拉取某商户最近更新的订单。
    接口: GET /goodlife/v1/akte/order/query/
    用 update_order_start_time/end_time 秒级时间窗做增量, 分页 page_num/page_size。
    token 失效时自动强制刷新并重试一次。
    """
    retried = {"flag": False}

    def _fetch_pages(t):
        d = cfg["douyin"]
        lookback = int(lookback_minutes if lookback_minutes is not None
                       else cfg["sync"].get("lookback_minutes", 60))
        end = int(time.time())
        since = end - lookback * 60
        page_size = int(d.get("page_size", 50))
        orders = []
        page = 1
        while True:
            resp = requests.get(
                OPEN_DOUYIN_BASE + d.get("order_query_path", ORDER_QUERY_PATH),
                headers={"access-token": t, "content-type": "application/json"},
                params={
                    "account_id": merchant["account_id"],
                    "page_num": page,
                    "page_size": page_size,
                    "update_order_start_time": since,
                    "update_order_end_time": end,
                }, timeout=20)
            body = resp.json() or {}
            # 错误可能出现在顶层 code/err_no, 也可能在 data.error_code / extra.error_code
            data = body.get("data") or {}
            err_code = None
            for k in (body.get("code"), body.get("err_no")):
                if isinstance(k, int) and k != 0:
                    err_code = k
            if isinstance(data, dict) and isinstance(data.get("error_code"), int) and data["error_code"] != 0:
                err_code = data["error_code"]
            if isinstance(body.get("extra"), dict) and isinstance(body["extra"].get("error_code"), int) \
                    and body["extra"]["error_code"] != 0:
                err_code = body["extra"]["error_code"]
            if err_code is not None:
                desc = (body.get("description") or (data.get("description") if isinstance(data, dict) else "")
                        or (body.get("extra") or {}).get("description") or "")
                raise RuntimeError(f"订单接口返回异常 errcode={err_code}: {desc} (logid={((body.get('extra') or {}).get('logid'))})")
            items = _resp_items(data)
            orders.extend(items)
            total = int(data.get("total") or 0)
            if not items or page * page_size >= total:
                break
            page += 1
        return [map_api_order(o) for o in orders]

    try:
        return _fetch_pages(token)
    except RuntimeError as e:
        if not retried["flag"] and _is_token_error(e):
            retried["flag"] = True
            token = get_client_token(cfg, force=True)  # token 失效: 强制刷新后重试一次
            return _fetch_pages(token)
        raise


def map_api_order(o):
    """把接口返回的订单字段映射成内部统一结构(字段名以官方文档为准, 此处做兼容)。"""
    sku = o.get("sku_info") or o.get("sku") or {}
    return {
        "order_id": o.get("order_id") or o.get("orderId") or o.get("id"),
        "goods": o.get("title") or o.get("goods_name") or sku.get("title") or sku.get("name"),
        "amount": o.get("pay_amount") or o.get("amount") or o.get("order_amount"),
        "status": o.get("order_status") or o.get("status") or o.get("status_str"),
        "customer": o.get("buyer_nick") or o.get("customer_name") or (o.get("buyer_info") or {}).get("nick_name"),
        "created_at": o.get("create_time") or o.get("created_at") or o.get("pay_time"),
        "shop": o.get("shop_name") or o.get("store_name"),
        "_raw": o,  # 保留原始结构, 供手机号提取用
    }


# ---------------- 手机号: 提取 + 解密 ----------------

def find_encrypted_phone(order_raw):
    """在订单原始结构中递归查找加密手机号字段。"""
    hits = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() in PHONE_ENCRYPT_KEYS and isinstance(v, str) and len(v) >= 16:
                    hits.append(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(order_raw)
    return hits[0] if hits else None


def _aes_key_iv(client_secret):
    """官方规则: 把 clientSecret 补齐/裁剪到 32 字节作为 AES-256 key, IV 取 key 前 16 字节。"""
    key = client_secret.encode("utf-8")
    if len(key) < 32:
        pad = 32 - len(key)
        left = pad // 2 + pad % 2
        key = (b"#" * left + key + b"#" * (pad - left))
    key = key[:32]
    return key, key[:16]


def decrypt_phone_local(cfg, cipher):
    """本地 AES-256-CBC 解密, 需要 pycryptodome。"""
    from Crypto.Cipher import AES  # pycryptodome
    _, secret = get_douyin_credentials(cfg)
    key, iv = _aes_key_iv(secret)
    c = AES.new(key, AES.MODE_CBC, iv)
    raw = c.decrypt(base64.b64decode(cipher))
    return raw[:-raw[-1]].decode("utf-8", errors="replace")  # 去 PKCS7 padding


def decrypt_phone_via_api(cfg, token, account_id, cipher):
    """回退方案: 官方批量解密接口。"""
    resp = requests.post(
        OPEN_DOUYIN_BASE + DECRYPT_BATCH_PATH,
        headers={"access-token": token, "content-type": "application/json",
                 "Rpc-Transit-Life-Account": account_id},
        json={"account_id": account_id, "cipher_texts": [cipher]}, timeout=15)
    body = resp.json() or {}
    data = body.get("data") or {}
    items = data.get("decrypt_results") or data.get("plain_texts") or []
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, str):
            return first
        return first.get("plain_text") or first.get("text") or ""
    raise RuntimeError(f"批量解密接口返回异常: {body}")


def attach_phone(cfg, orders, token, merchant):
    """按 douyin.phone_decrypt 策略给订单补明文手机号: local(默认) / api / off。"""
    mode = str(cfg["douyin"].get("phone_decrypt", "local")).lower()
    if mode == "off":
        return orders
    for o in orders:
        cipher = find_encrypted_phone(o.get("_raw") or {})
        if not cipher:
            continue
        try:
            if mode == "api":
                o["phone"] = decrypt_phone_via_api(cfg, token, merchant["account_id"], cipher)
            else:
                try:
                    o["phone"] = decrypt_phone_local(cfg, cipher)
                except ImportError:
                    o["phone"] = decrypt_phone_via_api(cfg, token, merchant["account_id"], cipher)
        except Exception as e:  # 解密失败不影响订单推送, 手机号留空
            print(f"[phone] 订单 {o.get('order_id')} 手机号解密失败: {e}")
        o.pop("_raw", None)
    return orders


# ---------------- 去重与格式化 ----------------

def filter_new(orders, cfg, state_file):
    # Docker 部署时通过 STATE_DIR 指向挂载卷, 保证去重状态持久化
    state_dir = os.environ.get("STATE_DIR") or BASE_DIR
    try:
        os.makedirs(state_dir, exist_ok=True)
    except OSError:
        state_dir = BASE_DIR
    state_path = os.path.join(state_dir, state_file)
    sent = set()
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                sent = set(json.load(f).get("sent_order_ids", []))
        except (json.JSONDecodeError, OSError):
            pass
    new = [o for o in orders if o.get("order_id") and str(o["order_id"]) not in sent]
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"sent_order_ids": sorted(sent | {str(o.get("order_id")) for o in new})[-5000:],
                   "updated_at": dt.datetime.now().isoformat(timespec="seconds")},
                  f, ensure_ascii=False, indent=2)
    return new


def fmt_amount(v):
    try:
        num = float(str(v).replace("¥", "").replace("￥", "").replace(",", "").strip())
        # 来客API金额常为分, 文件导出通常为元; >10000 且无小数时按分处理
        if num > 100000 and float(num).is_integer() and "." not in str(v) and "¥" not in str(v):
            num /= 100
        return f"¥{num:,.2f}"
    except (ValueError, TypeError):
        return str(v) if v else "-"


def fmt_time(v):
    s = str(v or "").strip()
    if s.isdigit():  # unix 时间戳
        try:
            ts = int(s)
            if ts > 10**12:
                ts //= 1000
            return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OverflowError, OSError):
            return s
    return s


FIELD_LABELS = {"order_id": "订单号", "goods": "商品", "amount": "金额", "status": "状态",
                "customer": "客户", "phone": "手机号", "created_at": "下单时间", "shop": "门店"}


def format_order_md(o, push_cfg):
    fields = push_cfg.get("fields", ["order_id", "goods", "amount", "status"])
    lines = []
    status = str(o.get("status") or "").strip()
    emoji = next((e for k, e in STATUS_EMOJI.items() if k in status), "")
    title = o.get("goods") or "(未识别商品名)"
    lines.append(f"### {emoji} 新订单：{title}")
    for f_ in fields:
        v = o.get(f_)
        if v in (None, ""):
            continue
        if f_ == "amount":
            v = fmt_amount(v)
        elif f_ == "created_at":
            v = fmt_time(v)
        lines.append(f"> **{FIELD_LABELS.get(f_, f_)}**：{v}")
    return "\n".join(lines)


def format_summary_md(orders, push_cfg):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    total = sum(float(str(o["amount"]).replace("¥", "").replace("￥", "").replace(",", "") or 0)
                for o in orders if str(o.get("amount", "")).replace(".", "").isdigit())
    lines = [f"### 📋 抖音来客订单同步（{now}）",
             f"> 本次新增 **{len(orders)}** 笔订单，合计约 **{fmt_amount(total)}**", ""]
    limit = int(push_cfg.get("max_orders_in_summary", 20))
    for i, o in enumerate(orders[:limit], 1):
        status = str(o.get("status") or "").strip()
        emoji = next((e for k, e in STATUS_EMOJI.items() if k in status), "")
        parts = [f"{i}. {emoji} **{(o.get('goods') or '-')}** — {fmt_amount(o.get('amount'))}",
                 f"{status or '-'}", fmt_time(o.get('created_at'))]
        if o.get("phone"):
            parts.append(f"📱 {o['phone']}")
        parts.append(f"单号 {o.get('order_id', '-')}")
        lines.append("｜".join(parts))
    if len(orders) > limit:
        lines.append(f"\n> ...另有 {len(orders) - limit} 笔未展示")
    return "\n".join(lines)


# ---------------- 消息构建与推送 ----------------

# ---------------- 消息模板 ----------------

SEP = "━━━━━━━━━━━━━━"


def _fmt_amount(v):
    try:
        return f'{float(str(v).replace("¥", "").replace("￥", "").replace(",", "")):g}'
    except (TypeError, ValueError):
        return v or "-"


def format_order_template(o):
    return "\n".join([
        "🛍️【新订单提醒】",
        SEP,
        "🎉 您有一笔新的客户订单，请及时处理！",
        f"🧾 订单编号：{o.get('order_id') or '-'}",
        f"👤 客户姓名：{o.get('customer') or '-'}",
        f"💰 订单金额：¥{_fmt_amount(o.get('amount'))}",
        f"📦 订单内容：{o.get('goods') or '-'}",
        f"🕒 下单时间：{o.get('created_at') or '-'}",
        SEP,
        "📲 请立即查看订单，并联系客户完成核销！",
        "✅ 处理完成后，请及时更新订单状态。",
    ])


def format_lead_template(o):
    src = o.get("shop") or "抖音来客"
    return "\n".join([
        "📣【新线索提醒】",
        SEP,
        "🎯 您有一条新的客户线索，请及时跟进！",
        f"👤 客户姓名：{o.get('customer') or '-'}",
        f"📞 联系电话：{o.get('phone') or '-'}",
        f"📍 线索来源：{src}",
        f"🕒 线索时间：{o.get('created_at') or '-'}",
        SEP,
        "☎️ 请立即拨打电话，主动邀约客户！",
        "✅ 跟进完成后，请及时更新线索状态。",
    ])


def format_summary_template(orders, style):
    """汇总模式: 一条消息含头部 + 每单核心字段块(受 max_orders_in_summary 限制)。"""
    blocks = []
    for o in orders[: int(20)]:
        if style == "order":
            blocks.append("\n".join([
                f"🧾 订单编号：{o.get('order_id') or '-'}",
                f"👤 客户姓名：{o.get('customer') or '-'}",
                f"💰 订单金额：¥{_fmt_amount(o.get('amount'))}",
                f"📦 订单内容：{o.get('goods') or '-'}",
                f"🕒 下单时间：{o.get('created_at') or '-'}",
            ]))
        else:
            blocks.append("\n".join([
                f"👤 客户姓名：{o.get('customer') or '-'}",
                f"📞 联系电话：{o.get('phone') or '-'}",
                f"📍 线索来源：{o.get('shop') or '抖音来客'}",
                f"🕒 线索时间：{o.get('created_at') or '-'}",
            ]))
    n = len(orders)
    head = ("🎉 " + ("您有 {} 笔新的客户订单，请及时处理！".format(n) if style == "order"
                    else "您有 {} 条新的客户线索，请及时跟进！".format(n)))
    tail = ("📲 请立即查看订单，并联系客户完成核销！" if style == "order"
            else "☎️ 请立即拨打电话，主动邀约客户！")
    title = "🛍️【订单汇总提醒】" if style == "order" else "📣【线索汇总提醒】"
    return "\n".join([title, SEP, head, SEP] + [b for blk in blocks for b in (blk, SEP)] + [tail])


def build_messages(orders, push_cfg):
    if not orders:
        return []
    mention = push_cfg.get("mention_mobile_list", [])
    suffix = " ".join(f"<@{m}>" if m != "@all" else "<@all>" for m in mention)
    if suffix:
        suffix = "\n" + suffix
    style = str(push_cfg.get("template", "default")).lower()
    if style in ("order", "lead"):
        fmt = format_order_template if style == "order" else format_lead_template
        if push_cfg.get("per_order", False):
            msgs = [{"msgtype": "markdown", "markdown": {"content": fmt(o) + suffix}}
                    for o in orders]
        else:
            msgs = [{"msgtype": "markdown",
                     "markdown": {"content": format_summary_template(orders, style) + suffix}}]
    elif push_cfg.get("per_order", False):
        msgs = [{"msgtype": "markdown", "markdown": {"content": format_order_md(o, push_cfg) + "\n" + suffix}}
                for o in orders]
    else:
        msgs = [{"msgtype": "markdown", "markdown": {"content": format_summary_md(orders, push_cfg) + "\n" + suffix}}]
    # 机器人单条 markdown 上限 4096 字节, 超长自动拆分
    result = []
    for m in msgs:
        content = m["markdown"]["content"]
        while len(content.encode("utf-8")) > 4000:
            cut = content.rfind("\n", 0, 1900)
            cut = cut if cut > 0 else 1900
            result.append({"msgtype": "markdown", "markdown": {"content": content[:cut]}})
            content = content[cut:]
        result.append({"msgtype": "markdown", "markdown": {"content": content}})
    return result


def send_to_wecom(messages, wecom_cfg, dry_run=False):
    """按 wecom.target 路由推送: internal(内部群webhook) / customer_group(外部客户群) / both。"""
    target = wecom_cfg.get("target", "internal")
    ok = True
    if target in ("internal", "both"):
        ok = send_to_internal(messages, wecom_cfg, dry_run=dry_run) and ok
    if target in ("customer_group", "both"):
        ok = send_to_customer_groups(messages, wecom_cfg, dry_run=dry_run) and ok
    return ok


def send_to_internal(messages, wecom_cfg, dry_run=False):
    url = wecom_cfg.get("webhook_url", "")
    if dry_run:
        for i, m in enumerate(messages, 1):
            print(f"--- 消息 {i}/{len(messages)} (dry-run, 未发送) ---")
            print(m["markdown"]["content"])
            print()
        return True
    if "qyapi.weixin.qq.com" not in url:
        sys.exit("尚未配置企业微信群机器人 Webhook, 请编辑 config.json 的 wecom.webhook_url。")
    ok = True
    for i, m in enumerate(messages, 1):
        resp = requests.post(url, json=m, timeout=15)
        data = resp.json()
        if data.get("errcode") != 0:
            ok = False
            print(f"消息 {i} 发送失败: {data}")
        else:
            print(f"消息 {i}/{len(messages)} 已发送到企业微信群 ✔")
        if i < len(messages):
            time.sleep(1)  # 机器人限频: 每分钟20条
    return ok


# ---------------- 外部客户群推送(客户联系-企业群发) ----------------

def get_wecom_token(wecom_cfg):
    """用自建应用凭证换取企业微信 access_token(有效期2小时, 脚本内即用即取)。"""
    if "在此填入" in (wecom_cfg.get("corpid", "") + wecom_cfg.get("secret", "")):
        sys.exit("尚未配置企业微信应用凭证, 请编辑 config.json 的 wecom.corpid / wecom.secret。")
    resp = requests.get(f"{WECOM_API_BASE}/gettoken", params={
        "corpid": wecom_cfg["corpid"], "corpsecret": wecom_cfg["secret"],
    }, timeout=15)
    data = resp.json()
    if data.get("errcode") != 0:
        sys.exit(f"获取企业微信 access_token 失败: {data}")
    return data["access_token"]


def list_customer_groups(wecom_cfg):
    """列出应用可见范围内成员的客户群(chat_id + 群名), 供配置 chat_id_list 用。"""
    token = get_wecom_token(wecom_cfg)
    groups, cursor = [], ""
    while True:
        resp = requests.post(f"{WECOM_API_BASE}/externalcontact/groupchat/list",
                             params={"access_token": token},
                             json={"cursor": cursor, "limit": 100, "status_filter": 0},
                             timeout=15)
        data = resp.json()
        if data.get("errcode") != 0:
            sys.exit(f"获取客户群列表失败: {data}")
        groups.extend(data.get("group_chat_list") or [])
        cursor = data.get("next_cursor") or ""
        if not cursor:
            break
    # groupchat/list 只返回 chat_id, 再逐个取群名(失败不影响列表输出)
    out = []
    for g in groups:
        chat_id = g.get("chat_id")
        name = ""
        try:
            detail = requests.post(f"{WECOM_API_BASE}/externalcontact/groupchat/get",
                                   params={"access_token": token},
                                   json={"chat_id": chat_id, "need_name": 1},
                                   timeout=15).json()
            if detail.get("errcode") == 0:
                name = (detail.get("group_chat") or {}).get("name", "")
        except requests.RequestException:
            pass
        out.append({"chat_id": chat_id, "name": name})
    return out


def md_to_text(md):
    """群发接口不支持 markdown, 去掉格式符号转为纯文本。"""
    import re
    lines = []
    for line in md.splitlines():
        line = re.sub(r"<@\w+>|<@all>", "", line)          # 去 @提醒
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)  # 链接只留文字
        line = re.sub(r"[*_`~#>|]+", "", line)             # 去格式符号
        lines.append(line.strip())
    return "\n".join(l for l in lines if l)


def chunk_text(text, max_bytes=1900):
    """按 UTF-8 字节数切块(群发文本建议控制在 2048 字节内), 尽量在换行处断开。"""
    chunks = []
    while len(text.encode("utf-8")) > max_bytes:
        cut = text.rfind("\n", 0, max_bytes // 2)
        cut = cut if cut > 0 else max_bytes // 2
        while len(text[:cut].encode("utf-8")) > max_bytes and cut > 1:
            cut -= 1
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def send_to_customer_groups(messages, wecom_cfg, dry_run=False):
    """通过企业群发 API 向客户群推送。注意: 需群主在手机端确认后才真正发出。"""
    chat_ids = wecom_cfg.get("chat_id_list") or []
    if not chat_ids:
        sys.exit("尚未配置客户群 ID, 请编辑 config.json 对应商户的 wecom.chat_id_list。"
                 "可运行 python sync.py --list-groups 查询群列表。")
    if dry_run:
        for i, m in enumerate(messages, 1):
            for j, part in enumerate(chunk_text(md_to_text(m["markdown"]["content"])), 1):
                print(f"--- 客户群群发 {i}/{len(messages)} 第{j}段 (dry-run, 未创建任务) ---")
                print(part)
                print()
        return True
    token = get_wecom_token(wecom_cfg)
    sender = wecom_cfg.get("sender") or None
    ok = True
    i = 0
    for m in messages:
        for part in chunk_text(md_to_text(m["markdown"]["content"])):
            i += 1
            payload = {"chat_type": "group", "chat_id_list": chat_ids,
                       "text": {"content": part}}
            if sender:
                payload["sender"] = sender
            resp = requests.post(f"{WECOM_API_BASE}/externalcontact/add_msg_template",
                                 params={"access_token": token}, json=payload, timeout=15)
            data = resp.json()
            if data.get("errcode") != 0:
                ok = False
                print(f"客户群群发任务 {i} 创建失败: {data}")
            else:
                fail = data.get("fail_list") or []
                msg = f"客户群群发任务 {i} 已创建 ✔ (待群主在手机端「群发助手」确认发送)"
                if fail:
                    ok = False
                    msg += f", 未覆盖的群: {fail}"
                print(msg)
            time.sleep(1)
    return ok


# ---------------- 单商户执行 ----------------

def state_file_for(merchant):
    if merchant.get("account_id"):
        return f"state_{merchant['account_id']}.json"
    return "state.json"


def process_merchant(cfg, merchant, orders, dry_run=False, all_mode=False):
    """去重 -> 构建消息 -> 按商户自己的 wecom 配置推送。"""
    tag = f"[{merchant['name']}]"
    if all_mode or dry_run:
        new_orders = orders
    else:
        new_orders = filter_new(orders, cfg, state_file_for(merchant))
    print(f"{tag} 待推送 {len(new_orders)} 笔新订单")
    messages = build_messages(new_orders, merchant["push"])
    if not messages:
        print(f"{tag} 没有需要推送的订单。")
        return True
    return send_to_wecom(messages, merchant["wecom"], dry_run=dry_run)


# ---------------- 常驻服务模式 ----------------

def watch_and_push_files(cfg, dry_run=False):
    """扫描 data/incoming/ 下的订单文件, 逐个推送后移入 processed/。"""
    cfg_dir = cfg.get("serve", {}).get("watch_dir", "data/incoming")
    incoming = os.path.join(BASE_DIR, cfg_dir)
    processed = os.path.join(BASE_DIR, os.path.dirname(cfg_dir), "processed")
    os.makedirs(incoming, exist_ok=True)
    os.makedirs(processed, exist_ok=True)
    files = [f for f in os.listdir(incoming)
             if os.path.splitext(f)[1].lower() in (".csv", ".xlsx", ".xls")]
    for fname in files:
        path = os.path.join(incoming, fname)
        print(f"[serve] 发现导出文件: {fname}")
        try:
            orders = read_orders_file(path)
            merchant = pick_merchant(normalize_merchants(cfg), cfg.get("serve", {}).get("merchant"))
            ok = process_merchant(cfg, merchant, orders, dry_run=dry_run)
            # 推送成功(或无新订单)后归档, 避免重复处理
            if ok:
                stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                os.replace(path, os.path.join(processed, f"{stamp}_{fname}"))
        except SystemExit as e:
            print(f"[serve] 配置错误: {e}")
            break
        except Exception as e:  # 单文件失败不影响服务运行
            print(f"[serve] 处理 {fname} 失败: {e}")


def run_server(cfg, dry_run=False, once=False):
    interval = int(cfg.get("serve", {}).get("interval_minutes", 30))
    mode = cfg.get("mode", "file")
    print(f"[serve] 常驻服务已启动: 模式={mode}, 每 {interval} 分钟执行一次"
          + ("(dry-run)" if dry_run else ""))
    while True:
        try:
            if mode == "api":
                try:
                    token = get_client_token(cfg)
                    for merchant in normalize_merchants(cfg):
                        if not merchant["account_id"]:
                            print(f"[serve] 商户 {merchant['name']} 未配置 account_id, 跳过")
                            continue
                        try:
                            orders = fetch_orders_api(cfg, merchant, token)
                            print(f"[serve][{merchant['name']}] API 拉取到 {len(orders)} 笔订单")
                            orders = attach_phone(cfg, orders, token, merchant)
                            process_merchant(cfg, merchant, orders, dry_run=dry_run)
                        except Exception as e:
                            print(f"[serve][{merchant['name']}] 本轮执行异常: {e}")
                except SystemExit as e:
                    print(f"[serve] API 模式未就绪, 跳过本轮: {e}")
            else:
                watch_and_push_files(cfg, dry_run=dry_run)
        except Exception as e:
            print(f"[serve] 本轮执行异常: {e}")
        if once:
            print("[serve] 单次执行完成, 退出 (--once)")
            return
        time.sleep(interval * 60)


def main():
    ap = argparse.ArgumentParser(description="抖音来客订单同步到企业微信群")
    ap.add_argument("--file", help="订单导出文件(CSV/Excel)")
    ap.add_argument("--api", action="store_true", help="使用API模式拉单")
    ap.add_argument("--dry-run", action="store_true", help="只打印消息, 不发送")
    ap.add_argument("--all", action="store_true", help="忽略去重记录, 全部推送")
    ap.add_argument("--serve", action="store_true", help="常驻服务模式(定时执行, 适合服务器部署)")
    ap.add_argument("--once", action="store_true", help="配合 --serve 只执行一轮后退出(测试用)")
    ap.add_argument("--list-groups", action="store_true", help="列出企业微信客户群(chat_id/群名), 用于配置 chat_id_list")
    ap.add_argument("--merchant", help="多商户时指定商户(按 name 或 1-based 序号), 默认第一个")
    args = ap.parse_args()

    cfg = load_config()
    merchants = normalize_merchants(cfg)

    if args.list_groups:
        merchant = pick_merchant(merchants, args.merchant)
        if not merchant["wecom"]:
            sys.exit("所选商户未配置 wecom。")
        groups = list_customer_groups(merchant["wecom"])
        for g in groups:
            print(f"{g['chat_id']}  {g['name'] or '(未取到群名)'}")
        print(f"\n共 {len(groups)} 个客户群。把目标群的 chat_id 填入该商户 wecom.chat_id_list 即可。")
        return

    if args.serve:
        run_server(cfg, dry_run=args.dry_run, once=args.once)
        return

    mode = "api" if args.api else ("file" if args.file else cfg.get("mode", "file"))

    if mode == "api":
        token = get_client_token(cfg)
        for merchant in merchants:
            print(f"== 商户: {merchant['name']} (account_id={merchant['account_id'] or '未配置'}) ==")
            if not merchant["account_id"]:
                print("未配置 account_id, 跳过。")
                continue
            orders = fetch_orders_api(cfg, merchant, token)
            print(f"API 拉取到 {len(orders)} 笔订单")
            orders = attach_phone(cfg, orders, token, merchant)
            process_merchant(cfg, merchant, orders, dry_run=args.dry_run, all_mode=args.all)
    else:
        path = args.file
        if not path:
            sys.exit("file 模式请通过 --file 指定订单文件, 或在 config.json 设置后运行 python sync.py --file <路径>")
        orders = read_orders_file(path)
        print(f"从文件读取到 {len(orders)} 笔订单: {path}")
        merchant = pick_merchant(merchants, args.merchant)
        process_merchant(cfg, merchant, orders, dry_run=args.dry_run, all_mode=args.all)


if __name__ == "__main__":
    main()

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
  - 内部群: 走群机器人 Webhook(简单可靠, 无需认证/备案)
  - 外部客户群(含微信用户): 群机器人不支持, 走「客户联系-企业群发」API,
    群主需在手机端「群发助手」确认后消息才会发出,
    且每个客户群每天默认只能接收 1 条群发(可在群发助手调整规则)
  - 普通微信群(零备案通道): target=outbox, 消息只入本地待发队列,
    由 Windows 端 wx_relay.py 用普通微信号发送后回报状态
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

import storage

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


def _phone_lines(o, push_cfg=None):
    """手机号是否展示, 统一由 push.fields 决定(不写就不展示), 订单上没解出号码也不展示。"""
    if "phone" not in ((push_cfg or {}).get("fields") or []):
        return []
    phone = o.get("phone")
    return [f"📞 联系电话：{phone}"] if phone else []


def format_order_template(o, push_cfg=None):
    return "\n".join([
        "🛍️【新订单提醒】",
        SEP,
        "🎉 您有一笔新的客户订单，请及时处理！",
        f"🧾 订单编号：{o.get('order_id') or '-'}",
        f"👤 客户姓名：{o.get('customer') or '-'}",
        *_phone_lines(o, push_cfg),
        f"💰 订单金额：¥{_fmt_amount(o.get('amount'))}",
        f"📦 订单内容：{o.get('goods') or '-'}",
        f"🕒 下单时间：{o.get('created_at') or '-'}",
        SEP,
        "📲 请立即查看订单，并联系客户完成核销！",
        "✅ 处理完成后，请及时更新订单状态。",
    ])


def format_lead_template(o, push_cfg=None):
    src = o.get("shop") or "抖音来客"
    return "\n".join([
        "📣【新线索提醒】",
        SEP,
        "🎯 您有一条新的客户线索，请及时跟进！",
        f"👤 客户姓名：{o.get('customer') or '-'}",
        *_phone_lines(o, push_cfg),
        f"📍 线索来源：{src}",
        f"🕒 线索时间：{o.get('created_at') or '-'}",
        SEP,
        "☎️ 请立即拨打电话，主动邀约客户！",
        "✅ 跟进完成后，请及时更新线索状态。",
    ])


def format_summary_template(orders, style, push_cfg=None):
    """汇总模式: 一条消息含头部 + 每单核心字段块(受 max_orders_in_summary 限制)。"""
    blocks = []
    for o in orders[: int(20)]:
        if style == "order":
            blocks.append("\n".join([
                f"🧾 订单编号：{o.get('order_id') or '-'}",
                f"👤 客户姓名：{o.get('customer') or '-'}",
                *_phone_lines(o, push_cfg),
                f"💰 订单金额：¥{_fmt_amount(o.get('amount'))}",
                f"📦 订单内容：{o.get('goods') or '-'}",
                f"🕒 下单时间：{o.get('created_at') or '-'}",
            ]))
        else:
            blocks.append("\n".join([
                f"👤 客户姓名：{o.get('customer') or '-'}",
                *_phone_lines(o, push_cfg),
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
            msgs = [{"msgtype": "markdown", "markdown": {"content": fmt(o, push_cfg) + suffix}}
                    for o in orders]
        else:
            msgs = [{"msgtype": "markdown",
                     "markdown": {"content": format_summary_template(orders, style, push_cfg) + suffix}}]
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


def send_to_wecom(messages, wecom_cfg, dry_run=False, merchant=None):
    """按 wecom.target 路由推送。

    outbox        主通道: 只入本地待发队列, 由 wx_relay*.py 用微信号发到**微信群**(全自动)
    internal      备用: 内部群机器人 Webhook(无需认证/备案, 但只支持企微内部群)
    customer_group 备用: 企业群发 API(需企业认证 + 可信域名/可信IP, 且要群主手动确认)
    both          备用: internal + customer_group

    为什么默认值是 outbox 而不是 internal: 本项目的目标群是「微信群」(企微体系里叫
    外部客户群 —— 群主是企微成员、成员里含微信客户, 在微信侧就是个普通群), 而外部群
    不支持群机器人、企业群发又必须人工确认, 只有微信号中继能做到全自动。
    """
    target = str(wecom_cfg.get("target") or "outbox").lower()
    ok = True
    if target in ("internal", "both"):
        ok = send_to_internal(messages, wecom_cfg, dry_run=dry_run) and ok
    if target in ("customer_group", "both"):
        ok = send_to_customer_groups(messages, wecom_cfg, dry_run=dry_run) and ok
    if target in ("outbox", "wechat_group", "wechat"):
        ok = send_to_outbox(messages, wecom_cfg, merchant=merchant, dry_run=dry_run) and ok
    if target not in ("internal", "customer_group", "both", "outbox", "wechat_group", "wechat"):
        sys.exit(f"未知的推送目标 target={target!r}, 可选: internal / customer_group / outbox / both")
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


def phone_in_text(text):
    """文本里是否出现过疑似手机号(11 位大陆号码)。"""
    import re
    return bool(re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", text or ""))


# 【可选的安全提醒】群名里出现这些词 → 认为该群是「多客户群」(群里坐着多个客户,
# 消息对所有客户可见), 才会提示「这条消息里的手机号/客户姓名会被别的客户看到」。
# 判断只看【目标群名称】, 不看消息内容; 只提醒, 不拦截, 不改内容。
#
# 本项目实际场景(2026-09-20 与业主确认):
#   目标群是【门店群】, 群成员 = 代运营方 + 美业企业老板 + 店长, 群内没有别的客户。
#   客户是通过抖音来客留资/下单的, 群只是内部接收点 → 提醒没有意义, 已在 config.json
#   里把 privacy_multi_customer_keywords 显式置为 [] 关掉。手机号照常展示。
#
# 关键词支持通配符: * = 任意多个字符, ? = 正好一个字符(不加通配符就是普通子串包含, 忽略大小写)。
# 例: 群名形如「品牌-省-市+门店」时, 写一条「某某品牌-*」可覆盖该品牌全部门店群 ——
#     这是通配符用法【示例】, 是否要加请按自己的群名确认, 不要照抄。
# 想彻底关掉提醒: 显式置为 []; 也可在 merchants[].wecom 里按商户覆盖。
DEFAULT_MULTI_CUSTOMER_KEYWORDS = [
    "客户群", "客户服务群", "客服群", "顾客群", "会员群", "福利群", "粉丝群", "用户群", "VIP群",
]


def _kw_matches(keyword, name):
    """单个关键词是否命中群名(忽略大小写)。支持 * 和 ? 通配符。"""
    import re
    kw = str(keyword or "").strip().lower()
    if not kw:
        return False
    if "*" not in kw and "?" not in kw:
        return kw in name
    pattern = "".join(
        ".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in kw
    )
    return re.search(pattern, name) is not None


def matched_keywords(group_name, keywords=None):
    """返回群名里命中的「多客户群」关键词列表(空列表 = 不是多客户群)。

    关键词支持 * / ? 通配符; 传 [] 表示不做这类判断。
    """
    name = (group_name or "").strip().lower()
    kws = DEFAULT_MULTI_CUSTOMER_KEYWORDS if keywords is None else (keywords or [])
    if not name:
        return []
    return [str(k).strip() for k in kws if _kw_matches(k, name)]


def is_multi_customer_group(group_name, keywords=None):
    """按【群名称】判断该群是否可能坐着多个客户(消息对所有客户可见)。

    keywords 传 [] 表示不做这类判断, 一律返回 False(即不再提醒)。
    """
    return bool(matched_keywords(group_name, keywords))


# 隐私键的默认值。配置里"没写"= 用默认; 显式写成 [] = 关掉该项。
PRIVACY_DEFAULTS = {
    "privacy_multi_customer_keywords": DEFAULT_MULTI_CUSTOMER_KEYWORDS,
    "privacy_warn_fields": ["phone"],
}


def wecom_with_privacy_defaults(wecom_cfg):
    """给 wecom 配置补上隐私默认值(仅用于界面展示与落盘, 不改判定逻辑)。"""
    out = dict(wecom_cfg or {})
    for key, default in PRIVACY_DEFAULTS.items():
        if out.get(key) is None:
            out[key] = list(default)
    return out


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


# ---------------- 零备案通道: 普通微信群(待发队列) ----------------

TEST_MERCHANT = "链路测试"
_last_test_stamp_ms = 0


def _next_test_stamp():
    """给测试消息生成一个「一定不会和上一条重复」的时间戳。

    队列按内容去重, 同一毫秒连点两次会被当成重复内容丢掉 —— 这里用单调递增兜底,
    保证每次点都真的能排进去一条。
    """
    global _last_test_stamp_ms
    ms = int(time.time() * 1000)
    if ms <= _last_test_stamp_ms:
        ms = _last_test_stamp_ms + 1
    _last_test_stamp_ms = ms
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S.") + f"{ms % 1000:03d}"


def build_test_message(group_name=""):
    """生成一条「链路测试」消息。

    用途: 在不动真实订单、不占用任何门店群的前提下, 验证
        服务器待发队列 → 微信号中继 → 微信群 → 回报
    整条链路是否通。内容里带毫秒级时间戳, 避免被队列的幂等键当成重复内容丢掉。
    """
    ts = _next_test_stamp()
    return "\n".join([
        "🧪【链路测试】",
        "--------------------------------",
        f"在「{group_name or '本群'}」里看到这条, 说明整条链路已经打通:",
        "抖音来客 → 服务器待发队列 → 微信号中继 → 微信群 ✔",
        f"发送时间: {ts}",
        "(仅测试, 可忽略; 不需要时在「待发队列」页签删掉即可)",
    ])


def enqueue_test_message(wecom_cfg, group=None):
    """把一条测试消息写进待发队列, 发往指定的测试群。

    默认用 wecom.test_group; 没配就报错提示, 不会误发到某个真实门店群。
    """
    target = (group or (wecom_cfg or {}).get("test_group") or "").strip()
    if not target:
        raise ValueError("没有可用的测试群名: 请在全局配置里填「测试群名称」"
                         "(例如 抖音本地生活订单通知), 或在本页输入框里临时指定。")
    content = build_test_message(target)
    n = storage.enqueue_outbox([content], merchant=TEST_MERCHANT, account_id="",
                               channel="test", target=target)
    # 定位刚入队的那一条, 方便界面/测试精确删掉它, 而不是按商户名批量清
    row_id = None
    for it in storage.list_outbox(status="pending", page_size=100).get("items", []):
        if (it.get("merchant") == TEST_MERCHANT and it.get("target") == target
                and it.get("content") == content):
            row_id = it.get("id")
            break
    pending = storage.outbox_stats().get("pending", 0)
    print(f"[outbox] 测试消息已入队 {n} 条 → 「{target}」(当前待发 {pending} 条),"
          f" 等中继发出后到群里看一眼即可。")
    return {"enqueued": n, "target": target, "content": content, "id": row_id,
            "pending": pending, "outbox": storage.outbox_stats()}


def send_to_outbox(messages, wecom_cfg, merchant=None, dry_run=False):
    """把消息写入本地待发队列, 由 Windows 端 wx_relay.py 用普通微信号发到微信群。

    为什么能用: 个人微信号没有开放接口, 但可以在你自己的 Windows 电脑上运行
    「微信 PC 客户端 + UIAutomation」把消息发出去 — 不经过企业微信任何审核,
    因此不需要企业认证、不需要可信域名、不需要 ICP 备案。
    代价: 属于客户端自动化操作, 有账号风险, 建议用小号 + 控制频率。
    """
    target = (wecom_cfg.get("wechat_group") or wecom_cfg.get("group_name") or "").strip()
    parts = []
    for m in messages:
        parts.extend(chunk_text(md_to_text(m["markdown"]["content"])))
    # 敏感信息提醒: 只看【目标群名称】, 不看消息内容。
    #   群名命中 privacy_multi_customer_keywords → 认定群里坐着多个客户(客户之间互相可见), 才提醒;
    #   不命中(门店内部群 / 工作群 / 一人一群的专属服务群等) → 一句话都不多说。
    # 只提醒、不拦截、也不动内容: 号码本来就是该商户自己客户的, 发不发由商家判断。
    kws = wecom_cfg.get("privacy_multi_customer_keywords")
    hits = matched_keywords(target, kws)
    if hits:
        warn_fields = wecom_cfg.get("privacy_warn_fields") or ["phone"]
        if "phone" in warn_fields and any(phone_in_text(p) for p in parts):
            print(f"[outbox] ⚠ 群「{target}」看着是多客户群(群名命中 {'/'.join(hits)}), 群内客户互相可见;"
                  " 这条消息里的手机号会同时被其他客户看到。"
                  " 若这个群其实只有店家与该客户, 把该商户 wecom.privacy_multi_customer_keywords 置为 [] 即可。")
        if "customer" in warn_fields and "customer" in ((merchant or {}).get("push", {}).get("fields") or []):
            print("[outbox] ⚠ 同上: 消息里带「客户姓名」, 群里其他客户也看得到。")
    if not parts:
        print("[outbox] 没有可入队的消息。")
        return True
    if dry_run:
        for i, p in enumerate(parts, 1):
            print(f"--- 待发队列 {i}/{len(parts)} (dry-run, 未入队) ---")
            print(p)
            print()
        return True
    if not target:
        sys.exit("未配置微信接收群名称, 请编辑 config.json 对应商户的 wecom.wechat_group"
                 "(必须与微信里的群名称完全一致)。")
    merchant = merchant or {}
    n = storage.enqueue_outbox(parts, merchant=merchant.get("name", ""),
                               account_id=merchant.get("account_id", ""),
                               channel="wechat_group", target=target)
    pending = storage.outbox_stats().get("pending", 0)
    print(f"[outbox] 已入队 {n} 条 → 微信群「{target}」(当前待发 {pending} 条), "
          f"等待 Windows 端中继发送。")
    return True


# ---------------- 单商户执行 ----------------

def state_file_for(merchant):
    if merchant.get("account_id"):
        return f"state_{merchant['account_id']}.json"
    return "state.json"


def process_merchant(cfg, merchant, orders, dry_run=False, all_mode=False, target_override=None):
    """去重 -> 构建消息 -> 按商户自己的 wecom 配置推送。target_override 可临时改推送通道。"""
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
    wecom_cfg = dict(merchant["wecom"])
    if target_override:
        wecom_cfg["target"] = target_override
    return send_to_wecom(messages, wecom_cfg, dry_run=dry_run, merchant=merchant)


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

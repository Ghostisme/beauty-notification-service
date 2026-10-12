"""真实接入检查。只记录检查结果，不保存平台令牌或客户资料。"""
import hashlib
import json
import time

from .domain import error_text, full_phone, normalize_order


def identity(db, account_id=""):
    values = [db.settings("douyin"), db.secret("douyin_secret"), str(account_id)]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save_check(db, key, state, detail, fingerprint, metrics=None):
    result = {"state": state, "detail": detail, "checked_at": time.time(),
              "identity": fingerprint, "metrics": metrics or {}}
    db.set_settings("connection_check_" + key, result)
    return {k: v for k, v in result.items() if k != "identity"}


def current_check(db, key, fingerprint):
    result = db.settings("connection_check_" + key)
    if result.get("identity") != fingerprint:
        return {"state": "unverified", "detail": "当前配置尚未通过真实接口验证", "checked_at": None}
    if time.time() - result.get("checked_at", 0) > 86400:
        return {"state": "unverified", "detail": "上次检查已超过 24 小时，请重新验证", "checked_at": result.get("checked_at")}
    return {k: v for k, v in result.items() if k != "identity"}


def check_douyin(db, client, enterprise_id=None):
    enterprise = None
    if enterprise_id is not None:
        enterprise = db.one("SELECT * FROM enterprises WHERE id=? AND is_test=0", (enterprise_id,))
        if not enterprise:
            raise ValueError("请选择正式企业，测试企业不连接抖音")
        if not enterprise["enabled"]:
            raise ValueError("请先启用需要检查的企业")
    app_identity = identity(db)
    fingerprint = identity(db, enterprise["account_id"]) if enterprise else app_identity
    key = "orders_" + str(enterprise_id) if enterprise else "douyin_app"
    try:
        client.token(force=True)
    except Exception as exc:
        detail = error_text(exc, (db.secret("douyin_secret"), getattr(client, "_token", "")))
        result = save_check(db, "douyin_app", "failed", detail, app_identity)
        if enterprise:
            result = save_check(db, key, "failed", "应用凭证验证失败：" + detail, fingerprint)
        return result
    result = save_check(db, "douyin_app", "ready", "已从抖音真实接口取得应用访问令牌；商家订单权限需逐家检查", app_identity)
    if not enterprise:
        return result
    try:
        cfg = db.settings("douyin")
        end = int(time.time()) - 3
        data = client.request("GET", cfg["order_path"], enterprise["account_id"], params={
            "account_id": enterprise["account_id"], "page_num": 1, "page_size": 5,
            "cursor": "0", "update_order_start_time": end - 1800, "update_order_end_time": end})
        records = client.order_items(data)
        metrics = {"sample_orders": len(records), "with_store": 0, "with_phone": 0, "with_package": 0}
        for raw in records:
            merchant = raw.get("merchant_info") if isinstance(raw.get("merchant_info"), dict) else {}
            if merchant.get("account_id") and str(merchant["account_id"]) != enterprise["account_id"]:
                raise ValueError("平台返回订单的商户账号与当前企业不一致")
            order = normalize_order(raw, cfg["amount_unit"])
            for field, name in (("poi_id", "with_store"), ("phone", "with_phone"), ("goods", "with_package")):
                metrics[name] += bool(full_phone(order[field])) if field == "phone" else bool(order[field])
        detail = f"真实订单查询成功，本次返回 {len(records)} 条样本；未写入订单、未生成通知"
        if records:
            detail += f"。含门店 {metrics['with_store']} 条、完整手机号 {metrics['with_phone']} 条、套餐 {metrics['with_package']} 条（未执行解密，打码号码不计入完整号码）"
        else:
            detail += "。当前时间窗无订单，字段可用性需在有真实订单后核对"
        return save_check(db, key, "ready", detail, fingerprint, metrics)
    except Exception as exc:
        detail = error_text(exc, (db.secret("douyin_secret"), getattr(client, "_token", "")))
        if getattr(exc, "code", "") == "2119005":
            detail += "；请让商家在来客后台授权，并在服务商后台同意授权"
        elif getattr(exc, "code", "") == "2190004":
            detail += "；请在开放平台应用详情的解决方案中申请订单查询权限"
        elif getattr(exc, "code", "") == "2119013":
            detail += "；请在服务商应用的服务器 IP 白名单中添加实际查询电脑或服务器的公网出口 IP"
            detail += "；使用代理或 VPN 分流时，请核对抖音请求实际走的出口，通用 IP 检测网站可能返回另一条线路的地址"
        return save_check(db, key, "failed", detail, fingerprint)


def report(db, demo=False):
    items = []

    def add(key, name, state, detail, checked_at=None, **extra):
        items.append({"key": key, "name": name, "state": state, "detail": detail,
                      "checked_at": checked_at, **extra})

    add("environment", "运行环境", "blocked" if demo else "ready",
        "离线演示环境，不连接真实抖音、不执行企微发送" if demo else "正式实例，使用独立业务数据库；未接通的环节会明确显示")
    cfg = db.settings("douyin")
    if cfg["client_key"] and db.secret("douyin_secret"):
        app = current_check(db, "douyin_app", identity(db))
        add("douyin_app", "抖音应用凭证", **{k: app[k] for k in ("state", "detail", "checked_at")}, check_enterprise_id=0)
    else:
        add("douyin_app", "抖音应用凭证", "unconfigured", "在接入设置填写真实服务商应用的 Client Key 和 Client Secret", check_enterprise_id=0)
    enterprises = db.rows("SELECT * FROM enterprises WHERE is_test=0 AND enabled=1 ORDER BY id")
    if not enterprises:
        add("orders", "商家授权与订单查询", "unconfigured", "添加已授权商家的真实根商户账号 ID，然后逐家验证订单查询")
    for enterprise in enterprises:
        check = current_check(db, "orders_" + str(enterprise["id"]), identity(db, enterprise["account_id"]))
        add("orders_" + str(enterprise["id"]), "订单查询 · " + enterprise["name"],
            **{k: check[k] for k in ("state", "detail", "checked_at")}, check_enterprise_id=enterprise["id"])
    stores = db.rows("SELECT s.* FROM stores s JOIN enterprises e ON e.id=s.enterprise_id WHERE e.is_test=0 AND e.enabled=1 AND s.enabled=1")
    bound = [s for s in stores if s["group_id"] and s["group_name"]]
    add("routing", "正式门店与群匹配", "ready" if stores and len(bound) == len(stores) else "unconfigured",
        f"{len(bound)} / {len(stores)} 家正式门店已绑定接收群；需与真实订单里的门店 ID 核对")
    if cfg["clue_enabled"]:
        for enterprise in enterprises:
            check = current_check(db, "clues_" + str(enterprise["id"]), identity(db, enterprise["account_id"]))
            add("clues_" + str(enterprise["id"]), "线索与完整手机号 · " + enterprise["name"],
                **{k: check[k] for k in ("state", "detail", "checked_at")})
    else:
        lead = db.settings("connection_check_lead_ingest")
        detail = "客资中心线索同步尚未开启；已有标准接收接口和手工录入"
        if lead.get("checked_at"):
            detail += "。最近收到外部留资接口请求：" + time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(lead["checked_at"] + 28800)) + "（仍需核对上游来源）"
        add("leads", "独立留资自动获取", "unconfigured", detail, lead.get("checked_at"))
    channel = db.settings("channel")
    if channel["mode"] == "relay":
        workers = db.rows("SELECT * FROM relay_workers WHERE last_seen>? ORDER BY last_seen DESC", (time.time() - 45,))
        ready = [w for w in workers if w["ready"] and json.loads(w["groups_json"])]
        scopes = [set(json.loads(w["groups_json"])) for w in ready]
        covered = {s["group_id"] for s in bound if any(s["group_id"] in scope for scope in scopes)}
        state = "ready" if ready and bound and len(covered) == len(bound) else ("partial" if ready else "unconfigured")
        detail = f"{len(ready)} 个发送端在线且就绪，覆盖 {len(covered)} / {len(bound)} 个正式门店群"
        if not ready:
            detail += "。" + ((workers[0]["detail"] or "请完成界面校准") if workers else "请在发送电脑连接并校准企微")
        elif not bound:
            detail += "。当前尚未绑定正式门店；测试群的连接单独验证"
        add("sender", "企微 Windows 发送端", state, detail, workers[0]["last_seen"] if workers else None)
    else:
        add("sender", "企微 HTTP 发送工具", "unverified" if channel["http_url"] else "unconfigured",
            "已填写地址，需通过真实发送回执验证" if channel["http_url"] else "请填写实际发送工具的地址")
    sent = db.one("SELECT COUNT(*) AS n,MAX(sent_at) AS latest FROM messages WHERE status='sent' AND result_source='sender' AND is_test=0")
    tests = db.one("SELECT COUNT(*) AS n FROM messages WHERE status='sent' AND result_source='sender' AND is_test=1")["n"]
    add("delivery", "实际业务发送结果", "ready" if sent["n"] else "unverified",
        f"{sent['n']} 条正式通知有发送端确认，{tests} 条测试通知有发送端确认；人工确认和离线示例不算自动发送证明", sent["latest"])
    scheduler, notifications = db.settings("scheduler"), db.settings("notifications")
    add("automation", "自动任务", "ready" if scheduler["enabled"] and notifications["delivery_enabled"] else "paused",
        f"自动同步{'已开启' if scheduler['enabled'] else '已暂停'}；自动发送{'已开启' if notifications['delivery_enabled'] else '已暂停'}")
    if demo:
        for item in items[1:]:
            item.update(state="blocked", detail="演示数据不能证明真实接通；请启动正式实例", checked_at=None)
    return {"demo": demo, "items": items}

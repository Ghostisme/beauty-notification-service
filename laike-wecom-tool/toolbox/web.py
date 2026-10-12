import functools
import hmac
import json
import os
import secrets
import shutil
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import __version__
from .db import Database, dumps
from .connections import check_douyin, report
from .defaults import SETTINGS, STATUS_LABELS, TEMPLATES, VARIABLES
from .domain import error_text, render, text, validate_template
from .engine import Conflict, Engine
from .testing import TEST_GROUP_ID, TEST_GROUP_NAME, TEST_POI_ID, prepare_test_group, test_group


def integer(value, low, high, label):
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是整数")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}必须是整数") from None
    if str(value).strip() != str(number) or not low <= number <= high:
        raise ValueError(f"{label}需在 {low} 到 {high} 之间")
    return number


def url(value, allow_empty=False):
    value = text(value, 2000)
    if allow_empty and not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("请填写有效的 HTTP/HTTPS 地址，凭证请填到令牌字段")
    if parsed.query:
        raise ValueError("接入地址不支持查询参数，请通过请求头传递凭证")
    return value.rstrip("/")


def create_app(directory=None, password=None, start_engine=False, demo=False):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    db = Database(directory or os.environ.get("TOOL_DATA_DIR", "data"), password or os.environ.get("ADMIN_PASSWORD"))
    app.secret_key = db.session_key
    app.config.update(MAX_CONTENT_LENGTH=2 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
                      PERMANENT_SESSION_LIFETIME=43200, JSON_AS_ASCII=False)
    app.json.ensure_ascii = False
    engine = Engine(db)
    app.extensions["db"] = db
    app.extensions["engine"] = engine
    app.config["DEMO_MODE"] = demo
    failures = defaultdict(deque)
    failures_lock = threading.Lock()
    connection_check_lock = threading.Lock()

    def admin(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            user = db.one("SELECT auth_version FROM users WHERE username=?", (session.get("username", ""),))
            if not user or session.get("auth_version") != user["auth_version"]:
                return jsonify(error="请先登录"), 401
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                if not hmac.compare_digest(session.get("csrf", ""), request.headers.get("X-CSRF-Token", "")):
                    return jsonify(error="页面会话已失效，请刷新后重试"), 403
            return fn(*args, **kwargs)
        return wrapped

    def bearer(key):
        def decorator(fn):
            @functools.wraps(fn)
            def wrapped(*args, **kwargs):
                expected = db.secret(key)
                supplied = request.headers.get("Authorization", "")
                if not expected or not hmac.compare_digest("Bearer " + expected, supplied):
                    return jsonify(error="接入令牌无效"), 401
                return fn(*args, **kwargs)
            return wrapped
        return decorator

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return value

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        if request.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(Conflict)
    def conflict(error):
        return jsonify(error=str(error)), 409

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(404)
    def missing(_):
        return jsonify(error="页面或接口不存在"), 404

    @app.errorhandler(413)
    def too_big(_):
        return jsonify(error="数据超过 2 MiB，请分批提交"), 413

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("request failed: %s", type(error).__name__)
        return jsonify(error="操作未完成，请查看服务日志后重试"), 500

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/health")
    def health():
        db.one("SELECT 1 AS ok")
        return jsonify(status="ok", version=__version__)

    @app.post("/api/login")
    def login():
        now = time.time()
        key = request.remote_addr or "local"
        with failures_lock:
            # 限制失败 IP 表大小，避免长时间运行时无限增长。
            if len(failures) > 2000:
                for old_key in list(failures):
                    if not failures[old_key] or failures[old_key][-1] < now - 600:
                        failures.pop(old_key, None)
            while failures[key] and failures[key][0] < now - 600:
                failures[key].popleft()
            if len(failures[key]) >= 10:
                return jsonify(error="登录尝试较多，请十分钟后再试"), 429
        data = body()
        password_value = data.get("password", "")
        if not isinstance(password_value, str) or len(password_value) > 500:
            raise ValueError("密码格式不正确")
        user = db.one("SELECT * FROM users WHERE username=?", (text(data.get("username"), 100),))
        if not user or not check_password_hash(user["password_hash"], password_value):
            with failures_lock:
                failures[key].append(now)
            return jsonify(error="账号或密码不正确"), 401
        with failures_lock:
            failures.pop(key, None)
        session.clear()
        session.update(username=user["username"], auth_version=user["auth_version"], csrf=secrets.token_urlsafe(24))
        session.permanent = True
        return jsonify(username=user["username"], csrf=session["csrf"])

    @app.get("/api/session")
    @admin
    def get_session():
        return jsonify(username=session["username"], csrf=session["csrf"], version=__version__, demo=demo)

    @app.post("/api/logout")
    @admin
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.post("/api/password")
    @admin
    def change_password():
        data = body()
        old = db.one("SELECT * FROM users WHERE username=?", (session["username"],))
        if not check_password_hash(old["password_hash"], str(data.get("current_password", ""))):
            raise ValueError("原密码不正确")
        new = str(data.get("new_password", ""))
        if not 12 <= len(new) <= 200:
            raise ValueError("新密码需要 12 到 200 个字符")
        with db.connect(write=True) as c:
            c.execute("UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE username=?", (generate_password_hash(new), session["username"]))
        bootstrap = db.directory / ".bootstrap-password"
        if bootstrap.exists():
            bootstrap.unlink()
        session.clear()
        db.audit("修改管理员密码")
        return jsonify(ok=True)

    @app.get("/api/dashboard")
    @admin
    def dashboard():
        counts = {r["status"]: r["count"] for r in db.rows("SELECT status,COUNT(*) AS count FROM messages GROUP BY status")}
        workers = db.rows("SELECT * FROM relay_workers ORDER BY last_seen DESC")
        for worker in workers:
            worker["online"] = time.time() - worker["last_seen"] < 45
            worker.pop("groups_json", None)
        runs = db.rows("SELECT * FROM task_runs ORDER BY id DESC LIMIT 8")
        for run in runs:
            run["details"] = json.loads(run["details"])
        stat = db.one("SELECT COUNT(*) AS total,SUM(CASE WHEN result_source='manual' THEN 1 ELSE 0 END) AS manual FROM messages WHERE status='sent' AND sent_at>=?", (time.time() - 86400,))
        disk = shutil.disk_usage(db.directory)
        db_size = sum(p.stat().st_size for p in db.directory.glob("tool.db*") if p.is_file())
        return jsonify(counts=counts, sent_today=stat["total"], manual_today=stat["manual"] or 0,
                       enterprises=db.one("SELECT COUNT(*) AS n FROM enterprises WHERE is_test=0")["n"],
                       stores=db.one("SELECT COUNT(*) AS n FROM stores s JOIN enterprises e ON e.id=s.enterprise_id WHERE e.is_test=0")["n"], workers=workers, runs=runs,
                       scheduler=db.settings("scheduler"), notifications=db.settings("notifications"),
                       channel_mode=db.settings("channel")["mode"], last_tick=engine.last_tick,
                       next_sync=engine.next_sync, sync_running=engine.sync_lock.locked(),
                       db_bytes=db_size, disk_free_bytes=disk.free, uptime_seconds=int(time.time() - engine.started_at),
                       labels=STATUS_LABELS, demo=demo, version=__version__)

    @app.get("/api/enterprises")
    @admin
    def enterprises():
        return jsonify(items=db.rows("SELECT e.*,(SELECT COUNT(*) FROM stores s WHERE s.enterprise_id=e.id) AS stores_count FROM enterprises e ORDER BY e.id"))

    def save_enterprise(data, enterprise_id=None):
        account = text(data.get("account_id"), 120)
        name = text(data.get("name"), 150)
        if not account or not name:
            raise ValueError("企业名称和抖音商户账号 ID 必填")
        if not demo and not account.isdigit():
            raise ValueError("抖音商户账号 ID 应为数字字符串")
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("启用状态必须是布尔值")
        with db.connect(write=True) as c:
            if c.execute("SELECT 1 FROM enterprises WHERE account_id=? AND id<>?", (account, enterprise_id or 0)).fetchone():
                raise ValueError("该商户账号已绑定")
            if enterprise_id:
                old = c.execute("SELECT * FROM enterprises WHERE id=?", (enterprise_id,)).fetchone()
                if not old:
                    raise ValueError("企业不存在")
                if old["account_id"] != account:
                    raise ValueError("商户账号绑定后不能修改，请另建企业")
                c.execute("UPDATE enterprises SET name=?,enabled=? WHERE id=?", (name, int(enabled), enterprise_id))
            else:
                enterprise_id = c.execute("INSERT INTO enterprises(account_id,name,enabled,created_at) VALUES (?,?,?,?)", (account, name, int(enabled), time.time())).lastrowid
            db.audit("保存企业", enterprise_id, name, c)
        return {"id": enterprise_id}

    @app.post("/api/enterprises")
    @admin
    def enterprise_create():
        return jsonify(save_enterprise(body())), 201

    @app.put("/api/enterprises/<int:enterprise_id>")
    @admin
    def enterprise_update(enterprise_id):
        return jsonify(save_enterprise(body(), enterprise_id))

    @app.get("/api/stores")
    @admin
    def stores():
        return jsonify(items=db.rows("SELECT s.*,e.name AS enterprise_name,e.account_id,e.is_test FROM stores s JOIN enterprises e ON e.id=s.enterprise_id ORDER BY e.id,s.id"))

    def save_store(data, store_id=None):
        enterprise_id = integer(data.get("enterprise_id"), 1, 2147483647, "企业 ID")
        values = [text(data.get(k), 200) for k in ("poi_id", "name", "group_id", "group_name")]
        if not values[0] or not values[1]:
            raise ValueError("门店名称和抖音门店 ID 必填")
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("启用状态必须是布尔值")
        with db.connect(write=True) as c:
            enterprise = c.execute("SELECT * FROM enterprises WHERE id=?", (enterprise_id,)).fetchone()
            if not enterprise:
                raise ValueError("企业不存在")
            if enterprise["is_test"] and (values[0], values[2], values[3]) != (TEST_POI_ID, TEST_GROUP_ID, TEST_GROUP_NAME):
                raise ValueError("专用测试门店的群绑定固定，请使用测试消息入口")
            if c.execute("SELECT 1 FROM stores WHERE enterprise_id=? AND poi_id=? AND id<>?", (enterprise_id, values[0], store_id or 0)).fetchone():
                raise ValueError("该企业下已绑定此抖音门店 ID")
            if values[2] and c.execute("SELECT 1 FROM stores WHERE group_id=? AND id<>?", (values[2], store_id or 0)).fetchone():
                raise ValueError("该接收群标识已绑定另一家门店")
            # Windows 发送端按精确群名定位，因此不同门店不接受重名目标群。
            if values[3] and c.execute("SELECT 1 FROM stores WHERE group_name=? AND id<>?", (values[3], store_id or 0)).fetchone():
                raise ValueError("接收群名称重复，请先给门店群设置唯一名称")
            if store_id:
                old = c.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
                if not old or old["enterprise_id"] != enterprise_id:
                    raise ValueError("门店不存在或不属于该企业")
                if old["poi_id"] != values[0]:
                    raise ValueError("门店 ID 绑定后不能修改，请新增门店")
                c.execute("UPDATE stores SET poi_id=?,name=?,group_id=?,group_name=?,enabled=? WHERE id=?", (*values, int(enabled), store_id))
            else:
                store_id = c.execute("INSERT INTO stores(enterprise_id,poi_id,name,group_id,group_name,enabled,created_at) VALUES (?,?,?,?,?,?,?)", (enterprise_id, *values, int(enabled), time.time())).lastrowid
            db.audit("保存门店", store_id, values[1], c)
        return {"id": store_id}

    @app.post("/api/stores")
    @admin
    def store_create():
        return jsonify(save_store(body())), 201

    @app.put("/api/stores/<int:store_id>")
    @admin
    def store_update(store_id):
        return jsonify(save_store(body(), store_id))

    @app.get("/api/templates")
    @admin
    def templates():
        return jsonify(items=db.rows("SELECT * FROM templates ORDER BY kind"), variables=VARIABLES,
                       status_events=db.settings("notifications")["status_events"])

    @app.put("/api/templates/<kind>")
    @admin
    def template_update(kind):
        if kind not in TEMPLATES:
            raise ValueError("通知类型不存在")
        data = body()
        template_body = validate_template(data.get("body"))
        missing_policy = data.get("missing", "omit")
        if missing_policy not in ("omit", "placeholder") or not isinstance(data.get("enabled"), bool):
            raise ValueError("模板设置格式不正确")
        with db.connect(write=True) as c:
            c.execute("UPDATE templates SET body=?,enabled=?,missing=?,updated_at=? WHERE kind=?", (template_body, int(data["enabled"]), missing_policy, time.time(), kind))
            db.audit("保存模板", kind, connection=c)
        return jsonify(ok=True)

    @app.post("/api/templates/preview")
    @admin
    def preview():
        data = body()
        template = {"body": validate_template(data.get("body")), "missing": data.get("missing", "omit")}
        sample = {"record_id": "DY-DEMO-20261012", "poi_name": "玥笙-辽宁-大连中山店", "customer": "示例客户",
                  "phone": "13800000000", "goods": "面部补水护理套餐", "quantity": "1", "amount": "¥99.00",
                  "status": "已支付", "created_time": time.time(), "event_time": time.time(), "intent": "面部护理",
                  "source": "抖音留资表单", "remark": "希望周末到店", "event_name": "核销成功通知",
                  "previous_status": "待使用", "current_status": "已核销", "refund_amount": "¥99.00"}
        return jsonify(text=render(template, sample, "玥笙示例企业"))

    @app.get("/api/config")
    @admin
    def config_get():
        settings = {k: db.settings(k) for k in SETTINGS}
        settings["douyin"]["secret_configured"] = bool(db.secret("douyin_secret"))
        settings["channel"]["token_configured"] = bool(db.secret("http_token"))
        return jsonify(settings)

    @app.get("/api/connections")
    @admin
    def connection_report():
        return jsonify(report(db, demo))

    @app.post("/api/connections/douyin/check")
    @admin
    def connection_check():
        if demo:
            raise Conflict("真实接入检查需要正式实例；离线演示不会调用抖音")
        data = body()
        enterprise_id = data.get("enterprise_id")
        if enterprise_id is not None:
            enterprise_id = integer(enterprise_id, 1, 2147483647, "企业 ID")
        if not connection_check_lock.acquire(blocking=False):
            raise Conflict("已有抖音连接检查正在进行，请等待结果")
        try:
            result = check_douyin(db, engine.client, enterprise_id)
            db.audit("检查真实抖音连接", enterprise_id or "app", result["state"])
            return jsonify(result)
        finally:
            connection_check_lock.release()

    @app.put("/api/config/<section>")
    @admin
    def config_update(section):
        if section not in SETTINGS:
            raise ValueError("配置项不存在")
        data = body()
        current = db.settings(section)
        allowed = set(SETTINGS[section]) | ({"client_secret"} if section == "douyin" else {"http_token"} if section == "channel" else set())
        if set(data) - allowed:
            raise ValueError("包含不支持的配置字段")
        clean = {**current, **{k: v for k, v in data.items() if k in SETTINGS[section]}}
        ranges = {"interval_seconds": (30, 86400), "lookback_minutes": (5, 10080), "max_age_minutes": (1, 10080),
                  "max_pages": (1, 1000), "history_days": (7, 3650), "timeout_seconds": (5, 60),
                  "max_attempts": (1, 10), "lease_seconds": (60, 900), "clue_lookback_days": (1, 730)}
        for key, value in clean.items():
            if key in ranges:
                lo, hi = ranges[key]
                if section == "channel" and key == "interval_seconds":
                    lo, hi = 1, 300
                clean[key] = integer(value, lo, hi, key)
            elif isinstance(SETTINGS[section].get(key), bool) and not isinstance(value, bool):
                raise ValueError(f"{key} 必须是布尔值")
        if section == "notifications":
            if clean["order_trigger"] not in ("paid", "created"):
                raise ValueError("新订单触发条件仅支持 paid/created")
            if not isinstance(clean["status_events"], list) or any(not isinstance(v, str) or v not in {"paid", "verified", "refunding", "refunded", "canceled"} for v in clean["status_events"]):
                raise ValueError("状态事件配置不正确")
            for key in ("verified_statuses", "refunded_statuses", "refunding_statuses"):
                if not isinstance(clean[key], list) or not clean[key] or len(clean[key]) > 20:
                    raise ValueError("券状态规则必须是非空数组")
                clean[key] = [integer(v, 0, 99999, key) for v in clean[key]]
        if section == "douyin":
            clean["base_url"] = url(clean["base_url"])
            for key in ("order_path", "decrypt_path", "clue_path"):
                if not isinstance(clean[key], str) or not clean[key].startswith("/") or "?" in clean[key] or len(clean[key]) > 500:
                    raise ValueError("接口路径必须以 / 开头")
            if clean["amount_unit"] not in ("fen", "yuan"):
                raise ValueError("金额单位仅支持 fen/yuan")
            if clean["clue_enabled"] and not clean["decrypt_enabled"]:
                raise ValueError("同步客资中心完整号码需要同时开启平台手机号解密")
            clean["client_key"] = text(clean["client_key"], 200)
            if data.get("client_secret"):
                db.set_secret("douyin_secret", text(data["client_secret"], 1000))
        if section == "channel":
            if clean["mode"] not in ("relay", "http"):
                raise ValueError("发送方式仅支持 relay/http")
            clean["http_url"] = url(clean["http_url"], allow_empty=True)
            if clean["lease_seconds"] <= clean["timeout_seconds"] + 10:
                raise ValueError("发送回执等待时间必须大于请求超时时间十秒以上")
            if data.get("http_token"):
                db.set_secret("http_token", text(data["http_token"], 1000))
        db.set_settings(section, clean)
        if section == "scheduler":
            engine.next_sync = time.time() + 2
        db.audit("保存配置", section)
        return jsonify(ok=True)

    @app.post("/api/connection-token/<name>")
    @admin
    def connection_token(name):
        if name not in ("relay", "ingest"):
            raise ValueError("令牌类型不存在")
        data = body()
        if data.get("rotate"):
            db.set_secret(name + "_token", secrets.token_urlsafe(32))
            db.audit("更新接入令牌", name)
        return jsonify(token=db.secret(name + "_token"))

    @app.get("/api/messages")
    @admin
    def messages():
        page = integer(request.args.get("page", "1"), 1, 1000000, "页码")
        page_size = integer(request.args.get("page_size", "20"), 1, 100, "每页数量")
        where, args = [], []
        for key in ("status", "category", "enterprise_id"):
            value = request.args.get(key)
            if value:
                where.append(f"m.{key}=?")
                args.append(value)
        keyword = text(request.args.get("keyword"), 100)
        if keyword:
            where.append("(e.record_id LIKE ? ESCAPE '\\' OR m.group_name LIKE ? ESCAPE '\\' OR m.body LIKE ? ESCAPE '\\' OR json_extract(e.payload,'$.order_id') LIKE ? ESCAPE '\\')")
            pattern = "%" + keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args.extend([pattern] * 4)
        clause = " WHERE " + " AND ".join(where) if where else ""
        base = " FROM messages m JOIN events e ON e.id=m.event_id JOIN enterprises n ON n.id=m.enterprise_id LEFT JOIN stores s ON s.id=m.store_id"
        total = db.one("SELECT COUNT(*) AS n" + base + clause, args)["n"]
        fields = "m.id,m.category,m.is_test,m.group_name,m.status,m.attempts,m.last_error,m.result_source,m.created_at,m.sent_at,m.version,m.next_attempt,e.event_name,e.record_id,n.name AS enterprise_name,s.name AS store_name"
        items = db.rows("SELECT " + fields + base + clause + " ORDER BY m.id DESC LIMIT ? OFFSET ?", (*args, page_size, (page - 1) * page_size))
        return jsonify(items=items, total=total, page=page, page_size=page_size, labels=STATUS_LABELS)

    @app.get("/api/messages/<int:message_id>")
    @admin
    def message_detail(message_id):
        return jsonify(engine.message_detail(message_id))

    @app.post("/api/messages/<int:message_id>/<action>")
    @admin
    def message_action(message_id, action):
        return jsonify(engine.manual_action(message_id, action, body()))

    @app.post("/api/tasks/run")
    @admin
    def run_task():
        if not demo:
            if not db.one("SELECT 1 FROM enterprises WHERE enabled=1 AND is_test=0"):
                raise ValueError("请先添加已授权的正式企业，再同步真实订单")
            if not db.settings("douyin")["client_key"] or not db.secret("douyin_secret"):
                raise ValueError("请先填写真实抖音应用的 Client Key 和 Client Secret")
        engine.launch_sync("manual")
        return jsonify(accepted=True), 202

    @app.get("/api/tasks")
    @admin
    def tasks():
        rows = db.rows("SELECT * FROM task_runs ORDER BY id DESC LIMIT 50")
        for row in rows:
            row["details"] = json.loads(row["details"])
        return jsonify(items=rows, running=engine.sync_lock.locked(), next_sync=engine.next_sync)

    @app.post("/api/manual/lead")
    @admin
    def manual_lead():
        data = body()
        data["type"] = "new_lead"
        result = engine.ingest_event(data)
        db.audit("手工录入留资", result.get("message_id", ""))
        return jsonify(result), 201

    @app.get("/api/test-group")
    @admin
    def test_group_get():
        return jsonify(test_group(db))

    @app.post("/api/test-group")
    @admin
    def test_group_prepare():
        return jsonify(prepare_test_group(db))

    @app.post("/api/test-message")
    @admin
    def test_message():
        data = body()
        store_id = integer(data.get("store_id"), 1, 2147483647, "测试门店 ID")
        result = engine.create_test_message(store_id, data.get("category", "new_order"))
        return jsonify(result), 201

    @app.post("/api/ingest")
    @bearer("ingest_token")
    def ingest():
        data = body()
        result = engine.ingest_event(data)
        if data.get("type") == "new_lead":
            db.set_settings("connection_check_lead_ingest", {"checked_at": time.time()})
        return jsonify(result)

    @app.post("/api/relay/heartbeat")
    @bearer("relay_token")
    def heartbeat():
        data = body()
        worker = text(data.get("worker_id"), 100)
        if not worker or not isinstance(data.get("ready"), bool):
            raise ValueError("worker_id 和 ready 必填")
        groups = data.get("groups", [])
        if not isinstance(groups, list) or len(groups) > 1000 or any(not isinstance(v, str) for v in groups):
            raise ValueError("groups 必须是群标识字符串数组，最多 1000 个")
        with db.connect(write=True) as c:
            c.execute("INSERT INTO relay_workers VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,last_seen=excluded.last_seen,ready=excluded.ready,detail=excluded.detail,groups_json=excluded.groups_json",
                      (worker, text(data.get("label") or worker, 100), time.time(), int(data["ready"]), text(data.get("detail"), 1000), dumps(groups)))
        return jsonify(ok=True, delivery_enabled=db.settings("notifications")["delivery_enabled"])

    @app.get("/api/relay/groups")
    @bearer("relay_token")
    def relay_groups():
        return jsonify(items=db.rows("SELECT s.id,s.group_id,s.group_name,s.name AS store_name,e.name AS enterprise_name FROM stores s JOIN enterprises e ON e.id=s.enterprise_id WHERE s.enabled=1 AND e.enabled=1 AND s.group_id<>'' AND s.group_name<>'' ORDER BY s.id"))

    @app.post("/api/relay/claim")
    @bearer("relay_token")
    def claim():
        data = body()
        worker_id = text(data.get("worker_id"), 100)
        worker = db.one("SELECT * FROM relay_workers WHERE id=?", (worker_id,))
        if not worker or not worker["ready"] or time.time() - worker["last_seen"] > 45:
            raise ValueError("发送端尚未就绪，请先上报有效心跳")
        if demo or db.settings("channel")["mode"] != "relay":
            return jsonify(job=None)
        groups = json.loads(worker["groups_json"])
        if not groups:
            return jsonify(job=None)
        return jsonify(job=engine.claim(worker_id, groups))

    @app.post("/api/relay/result")
    @bearer("relay_token")
    def relay_result():
        data = body()
        message_id = integer(data.get("message_id"), 1, 2147483647, "通知 ID")
        outcome = data.get("status")
        if outcome == "sent" and not data.get("group_id"):
            raise ValueError("发送成功回执必须携带实际群标识")
        return jsonify(engine.finish(message_id, data.get("lease_token"), outcome,
                                     data.get("detail", ""), data.get("remote_id", ""), data.get("group_id")))

    if start_engine:
        engine.start()
    return app

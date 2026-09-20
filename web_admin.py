# -*- coding: utf-8 -*-
"""
本地管理后台: 商户管理 / 订单数据管理 / 运行日志追踪 / 推送控制。

用法:
  python web_admin.py                 # http://127.0.0.1:8787 (默认仅本机)
  ADMIN_HOST=0.0.0.0 ADMIN_TOKEN=xxx python web_admin.py   # 服务器部署(建议配 nginx + https)
  ADMIN_PORT=9000 python web_admin.py

安全:
  - 设置 ADMIN_TOKEN(环境变量)或 config.json 的 admin_token 后, 所有 /api/* 需带
    请求头 X-Admin-Token: <token>; 未设置时仅本机使用。
  - 日志中手机号自动脱敏; 全部操作/推送/错误写入 SQLite(data/admin.db) 可追踪。
"""

import contextlib
import hashlib
import io
import json
import logging
import logging.handlers
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import storage
import sync

BASE_DIR = sync.BASE_DIR
INDEX_PATH = os.path.join(BASE_DIR, "web", "index.html")
HOST = os.environ.get("ADMIN_HOST", "127.0.0.1")
PORT = int(os.environ.get("ADMIN_PORT", "8787"))

# 文件日志(服务运行日志) + SQLite 操作日志(业务追踪)
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
logger = logging.getLogger("admin")
logger.setLevel(logging.INFO)
_fh = logging.handlers.RotatingFileHandler(os.path.join(BASE_DIR, "logs", "web_admin.log"),
                                           maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_fh)

storage.init()


def get_admin_token():
    tok = os.environ.get("ADMIN_TOKEN")
    if tok:
        return tok.strip()
    try:
        return (sync.load_config().get("admin_token") or "").strip() or None
    except Exception:
        return None


def _load_cfg():
    cfg = sync.load_config()
    if "merchants" not in cfg:
        cfg["merchants"] = []
    return cfg


def _save_cfg(cfg):
    with open(sync.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _summarize(data):
    """从返回结果提取一句摘要(脱敏后落日志)。"""
    try:
        if isinstance(data, dict):
            if "total" in data and "messages" in data:
                return f"拉单 {data.get('total')} 笔, 生成消息 {len(data.get('messages') or [])} 条"
            if "ok_push" in data:
                return f"fetched={data.get('fetched')} ok_push={data.get('ok_push')}"
            if "groups" in data:
                return f"客户群 {len(data['groups'])} 个"
            if "saved" in data:
                return "配置已保存"
            if "enqueued" in data:
                return f"链路测试消息入队 {data.get('enqueued')} 条 → 「{data.get('target')}」"
            if "rebinds" in data:
                rbs = data.get("rebinds") or []
                base = f"商户共 {len(data.get('merchants') or [])} 个"
                if rbs:
                    base += (f"; 群名重绑定 {sum(r['updated'] for r in rbs)} 条 → "
                             f"「{rbs[0]['to']}」")
                return base
            if "merchants" in data:
                return f"商户共 {len(data['merchants'])} 个"
            if "logs" in data:
                return f"日志 {data.get('total')} 条"
            if "orders" in data:
                return f"订单 {data.get('total')} 条"
            if "items" in data:
                return f"待发队列 {data.get('total')} 条"
            if "acked" in data:
                return f"中继回报 {data.get('acked')} 条 (ok={data.get('ok')})"
            if "retried" in data:
                return f"重置重发 {data.get('retried')} 条"
            if "deleted" in data:
                return f"删除待发 {data.get('deleted')} 条"
            if "rebound" in data:
                r = data["rebound"]
                return (f"群名重绑定: {r.get('updated')} 条改指「{r.get('to')}」"
                        f"(旧群名 {'/'.join(r.get('old_targets') or []) or '无'})")
            if "bindings" in data:
                bad = [b for b in data["bindings"] if b.get("stale_total")]
                return f"绑定检查 {len(data['bindings'])} 个商户, {len(bad)} 个存在旧群名残留"
    except Exception:
        pass
    return ""


def _run(action, fn, merchant=None):
    """统一包装: 捕获异常与 stdout, 写操作日志, 返回 {ok, data/error, log}。"""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            data = fn()
        storage.add_log("INFO", merchant, action, True,
                        _summarize(data) or buf.getvalue().strip()[:500])
        return {"ok": True, "data": data, "log": buf.getvalue().strip()}
    except SystemExit as e:
        detail = str(e) + "\n" + buf.getvalue().strip()
        storage.add_log("ERROR", merchant, action, False, detail)
        return {"ok": False, "error": str(e), "log": buf.getvalue().strip()}
    except Exception as e:
        detail = f"{type(e).__name__}: {e}\n{buf.getvalue().strip()}\n{traceback.format_exc(limit=4)}"
        storage.add_log("ERROR", merchant, action, False, detail)
        logger.error("%s failed: %s\n%s", action, e, traceback.format_exc(limit=4))
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "log": buf.getvalue().strip()}


# ---------------- API 实现 ----------------

def api_get_config():
    cfg = _load_cfg()
    # 隐私键没配时补上默认值, 让界面看到的是「实际生效」的那份, 避免保存时被写空。
    cfg["wecom"] = sync.wecom_with_privacy_defaults(cfg.get("wecom") or {})
    return {"config": cfg}


def _effective_groups(cfg):
    """算出每个商户「实际生效」的接收群名(商户级 > 全局), 用于识别群名变更。"""
    out = {}
    try:
        for m in sync.normalize_merchants(cfg):
            out[m["name"]] = (m["wecom"].get("wechat_group") or "").strip()
    except Exception:
        pass
    return out


def _rebind_changed(old_groups, new_groups, only=None, retry_failed=True):
    """群名一变, 顺手把待发队列里还指着旧群名、尚未发出的消息重新绑定到新群名。

    这就是「改一个字段就完成换群绑定」的实现: 不用去队列里逐条删。
    """
    rebinds = []
    for name, new_g in new_groups.items():
        if only is not None and name != only:
            continue
        old_g = (old_groups.get(name) or "").strip()
        if not new_g or not old_g or new_g == old_g:
            continue
        r = storage.rebind_outbox_target(name, new_g, old_target=old_g, retry_failed=retry_failed)
        if r["updated"] or r["merged"]:
            logger.info("群名重绑定 [%s] 「%s」→「%s」: 改 %s 条 / 合并重复 %s 条",
                        name, old_g, new_g, r["updated"], r["merged"])
            rebinds.append({"merchant": name, "from": old_g, **r})
    return rebinds


def api_save_config(cfg):
    json.dumps(cfg)
    old_groups = _effective_groups(_load_cfg())
    new_groups = _effective_groups(cfg)
    rebinds = _rebind_changed(old_groups, new_groups)
    _save_cfg(cfg)
    for rb in rebinds:
        print(f"[群名重绑定] 商户「{rb['merchant']}」: 「{rb['from']}」→「{rb['to']}」,"
              f" 队列中 {rb['updated']} 条已改指新群" +
              (f", 合并重复 {rb['merged']} 条" if rb["merged"] else ""))
    return {"saved": True, "rebinds": rebinds}


def api_group_binding():
    """列出每个商户的群绑定情况: 配置里绑的群 vs 队列里还没发出去的群名。

    群被改名后, 队列里会残留旧的群名 —— 这里就是用来一眼看出「哪条还指着旧名字」的。
    """
    cfg = _load_cfg()
    bindings = []
    for m in sync.normalize_merchants(cfg):
        configured = (m["wecom"].get("wechat_group") or "").strip()
        targets = storage.pending_targets(m["name"])
        stale = {t: v for t, v in targets.items() if t != configured}
        bindings.append({
            "merchant": m["name"],
            "target": m["wecom"].get("target") or "outbox",
            "configured_group": configured,
            "queued_targets": targets,
            "stale_targets": stale,
            "stale_total": sum(v["total"] for v in stale.values()),
            "ok_total": (targets.get(configured) or {}).get("total", 0),
        })
    return {"bindings": bindings}


def api_merchant_save(body):
    m = body.get("merchant") or {}
    if not (m.get("account_id") or "").strip():
        raise ValueError("account_id 不能为空")
    cfg = _load_cfg()
    merchants = cfg.setdefault("merchants", [])
    idx = body.get("index")
    clean = {k: m.get(k) for k in ("account_id", "name", "wecom", "push") if m.get(k) is not None}

    old_groups = _effective_groups(cfg)
    old_name = merchants[idx].get("name") or "" if (isinstance(idx, int) and 0 <= idx < len(merchants)) else ""

    if isinstance(idx, int) and 0 <= idx < len(merchants):
        merchants[idx].update(clean)
        new_name = merchants[idx].get("name") or ""
    else:
        merchants.append(clean)
        new_name = clean.get("name") or ""

    if old_name and new_name and old_name != new_name:
        n = storage.rename_outbox_merchant(old_name, new_name)
        if n:
            logger.info("商户改名 [%s] → [%s]: 队列中 %s 条记录一并改名", old_name, new_name, n)
            print(f"[商户改名] 「{old_name}」→「{new_name}」, 队列中 {n} 条记录一同改名。")

    rebinds = []
    if old_name == new_name and new_name:
        rebinds = _rebind_changed(old_groups, _effective_groups(cfg), only=new_name)
    for rb in rebinds:
        print(f"[群名重绑定] 商户「{rb['merchant']}」: 「{rb['from']}」→「{rb['to']}」,"
              f" 队列中 {rb['updated']} 条已改指新群" +
              (f", 合并重复 {rb['merged']} 条" if rb["merged"] else ""))

    _save_cfg(cfg)
    return {"merchants": merchants, "rebinds": rebinds}


def api_outbox_rebind(body):
    """手工「重新绑定」: 把某商户队列里还没发出去的消息, 全部改指到配置里当前的群名。

    用在群被改名、但配置是早前改的(那时还没自动重绑定)这一类历史遗留场景。
    """
    spec = (body.get("merchant") or "").strip()
    cfg = _load_cfg()
    m = sync.pick_merchant(sync.normalize_merchants(cfg), spec or None)
    to = (m["wecom"].get("wechat_group") or "").strip()
    if not to:
        raise ValueError(f"商户「{m['name']}」还没配「微信接收群名称」, "
                         "请先在商户卡里把新群名填好并保存, 再来重新绑定。")
    old = (body.get("from") or "").strip() or None
    r = storage.rebind_outbox_target(m["name"], to, old_target=old,
                                     retry_failed=bool(body.get("retry_failed", True)))
    print(f"[群名重绑定] 商户「{m['name']}」: 旧群名 {('/'.join(r['old_targets']) or '(无)')}"
          f" → 「{to}」, 改指 {r['updated']} 条" +
          (f", 合并重复 {r['merged']} 条" if r["merged"] else ""))
    return {"merchant": m["name"], "rebound": r}


def api_merchant_delete(body):
    idx = body.get("index")
    cfg = _load_cfg()
    merchants = cfg.get("merchants", [])
    if not (isinstance(idx, int) and 0 <= idx < len(merchants)):
        raise ValueError("商户序号无效")
    removed = merchants.pop(idx)
    _save_cfg(cfg)
    return {"removed": removed.get("name"), "merchants": merchants}


def _merchant_ctx(merchant_spec):
    cfg = _load_cfg()
    m = sync.pick_merchant(sync.normalize_merchants(cfg), merchant_spec)
    return cfg, m


def _fetch_and_store(cfg, m, lookback_minutes=None):
    """拉单 -> 解密手机号 -> 存库 -> 返回订单列表。"""
    token = sync.get_client_token(cfg)
    orders = sync.fetch_orders_api(cfg, m, token, lookback_minutes=lookback_minutes)
    orders = sync.attach_phone(cfg, orders, token, m)
    storage.upsert_orders(m["account_id"], m["name"], orders)
    return orders


def api_orders_preview(merchant_spec, lookback_minutes=None, limit=20, debug=False):
    """拉单 -> 解密 -> 存库 -> 生成消息模板(不推送、不写去重状态)。debug=1 时附原始响应字段。"""
    cfg, m = _merchant_ctx(merchant_spec)
    raw_items = None
    if debug:
        token = sync.get_client_token(cfg)
        raw_orders = sync.fetch_orders_api(cfg, m, token, lookback_minutes=lookback_minutes)
        raw_items = [o.get("_raw") for o in raw_orders[:3]]
    orders = _fetch_and_store(cfg, m, lookback_minutes)
    messages = sync.build_messages(orders, m["push"])
    brief = [{k: o.get(k) for k in ("order_id", "goods", "amount", "status", "phone", "created_at")}
             for o in orders]
    return {"merchant": m["name"], "account_id": m["account_id"],
            "total": len(orders), "orders": brief, "raw": raw_items,
            "messages": [x["markdown"]["content"] for x in messages][:limit]}


def api_push(body):
    """真实推送: 拉单存库 -> 走去重 -> 推送。dry_run=true 只打印消息不发送。"""
    cfg, m = _merchant_ctx(body.get("merchant"))
    orders = _fetch_and_store(cfg, m, body.get("lookback_minutes"))
    ok = sync.process_merchant(cfg, m, orders, dry_run=bool(body.get("dry_run")),
                               target_override=body.get("target") or None)
    return {"ok_push": ok, "fetched": len(orders)}


# ---------------- 待发队列(零备案通道: 普通微信号中继) ----------------

def api_outbox(qs):
    """Windows 中继轮询取件; 后台页面也用这个接口看队列。"""
    return storage.list_outbox(
        status=(qs.get("status") or [None])[0],
        merchant=(qs.get("merchant") or [None])[0],
        page=int((qs.get("page") or ["1"])[0]),
        page_size=int((qs.get("page_size") or ["50"])[0]))


def api_outbox_ack(body):
    ids = body.get("ids") or []
    ok = bool(body.get("ok"))
    n = storage.ack_outbox(ids, ok, err=body.get("err") or "")
    return {"acked": n, "ok": ok, "outbox": storage.outbox_stats()}


def api_outbox_retry(body):
    return {"retried": storage.retry_outbox(body.get("ids") or []),
            "outbox": storage.outbox_stats()}


def api_outbox_delete(body):
    return {"deleted": storage.delete_outbox(body.get("ids") or []),
            "outbox": storage.outbox_stats()}


def api_outbox_enqueue(body):
    """拉单 -> 去重 -> 构建消息 -> 只入待发队列(不调用企业微信任何接口)。"""
    cfg, m = _merchant_ctx(body.get("merchant"))
    orders = _fetch_and_store(cfg, m, body.get("lookback_minutes"))
    ok = sync.process_merchant(cfg, m, orders, target_override="outbox")
    return {"ok_push": ok, "fetched": len(orders), "outbox": storage.outbox_stats()}


def api_outbox_test(body):
    """往「测试群」塞一条链路测试消息(不碰任何门店群、不拉订单)。

    用来验证: 服务器队列 → 微信号中继 → 微信群 → 回报 是否已经通。
    """
    cfg = _load_cfg()
    wecom = dict(cfg.get("wecom") or {})
    group = (body.get("group") or "").strip()
    # 允许临时指定; 不指定就用全局配置里的测试群
    res = sync.enqueue_test_message(wecom, group=group or None)
    # 顺手把临时指定的群名记下来, 下次不用重填
    if group and group != wecom.get("test_group"):
        wecom["test_group"] = group
        cfg["wecom"] = wecom
        _save_cfg(cfg)
        res["saved_test_group"] = group
    return res


def api_test_douyin():
    cfg = _load_cfg()
    token = sync.get_client_token(cfg, force=True)
    return {"client_token_prefix": token[:12] + "...", "valid": True}


def api_test_wecom(merchant_spec):
    _, m = _merchant_ctx(merchant_spec)
    w = m["wecom"]
    if "在此填入" in (w.get("corpid", "") + w.get("secret", "")):
        raise ValueError("该商户未配置 corpid/secret(仅外部客户群企业群发需要)")
    token = sync.get_wecom_token(w)
    return {"access_token_prefix": token[:12] + "...", "valid": True}


def api_wecom_groups(merchant_spec):
    _, m = _merchant_ctx(merchant_spec)
    groups = sync.list_customer_groups(m["wecom"])
    return {"groups": groups}


def api_orders(qs):
    account_id = (qs.get("account_id") or [None])[0]
    if (qs.get("merchant") or [None])[0]:
        _, m = _merchant_ctx((qs.get("merchant") or [None])[0])
        account_id = m["account_id"]
    return storage.list_orders(
        account_id=account_id,
        keyword=(qs.get("keyword") or [""])[0],
        page=int((qs.get("page") or ["1"])[0]),
        page_size=int((qs.get("page_size") or ["50"])[0]))


def api_logs(qs):
    return storage.list_logs(
        merchant=(qs.get("merchant") or [None])[0],
        action=(qs.get("action") or [None])[0],
        level=(qs.get("level") or [None])[0],
        page=int((qs.get("page") or ["1"])[0]),
        page_size=int((qs.get("page_size") or ["50"])[0]))


# ---------------- HTTP 服务 ----------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.info("%s %s", self.address_string(), fmt % args)

    def _send(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _authed(self, qs):
        token = get_admin_token()
        if not token:
            return True
        supplied = self.headers.get("X-Admin-Token") or (qs.get("token") or [""])[0]
        return hashlib.sha256((supplied or "").encode()).hexdigest() == hashlib.sha256(token.encode()).hexdigest()

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                with open(INDEX_PATH, "rb") as f:
                    self._send(200, "text/html; charset=utf-8", f.read())
                return
            if path == "/api/health":
                self._json({"ok": True, "service": "dylk-wecom-admin",
                            "outbox": storage.outbox_stats()})
                return
            if not self._authed(qs):
                self._json({"ok": False, "error": "unauthorized: 缺少或错误的访问令牌(X-Admin-Token)"}, 401)
                return
            if path == "/api/config":
                self._json(_run("查看配置", api_get_config))
            elif path == "/api/outbox":
                self._json(_run("查看待发队列", lambda: api_outbox(qs),
                                merchant=(qs.get("merchant") or [None])[0]))
            elif path == "/api/orders":
                self._json(_run("查询订单库", lambda: api_orders(qs),
                                merchant=(qs.get("merchant") or [None])[0]))
            elif path == "/api/logs":
                self._json(_run("查询日志", lambda: api_logs(qs),
                                merchant=(qs.get("merchant") or [None])[0]))
            elif path == "/api/stats":
                self._json(_run("查询概览", storage.stats))
            elif path == "/api/orders/preview":
                merchant = (qs.get("merchant") or [None])[0]
                self._json(_run("拉单预览", lambda: api_orders_preview(
                    merchant,
                    lookback_minutes=int((qs.get("lookback_minutes") or ["0"])[0]) or None,
                    limit=int((qs.get("limit") or ["20"])[0]),
                    debug=(qs.get("debug") or ["0"])[0] == "1"), merchant=merchant))
            elif path == "/api/group/binding":
                self._json(_run("检查群绑定", api_group_binding))
            elif path == "/api/wecom/groups":
                merchant = (qs.get("merchant") or [None])[0]
                self._json(_run("查询客户群", lambda: api_wecom_groups(merchant), merchant=merchant))
            elif path == "/api/test/wecom":
                merchant = (qs.get("merchant") or [None])[0]
                self._json(_run("测试企微凭证", lambda: api_test_wecom(merchant), merchant=merchant))
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            logger.error("GET %s error: %s", path, traceback.format_exc(limit=3))
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)
        try:
            if not self._authed(qs):
                self._json({"ok": False, "error": "unauthorized: 缺少或错误的访问令牌(X-Admin-Token)"}, 401)
                return
            body = self._body()
            if path == "/api/config/save":
                self._json(_run("保存配置", lambda: api_save_config(body.get("config") or {})))
            elif path == "/api/merchant/save":
                self._json(_run("保存商户", lambda: api_merchant_save(body),
                                merchant=(body.get("merchant") or {}).get("name")))
            elif path == "/api/merchant/delete":
                self._json(_run("删除商户", lambda: api_merchant_delete(body),
                                merchant=(body.get("merchant") or {}).get("name")))
            elif path == "/api/push":
                merchant = body.get("merchant")
                self._json(_run("推送测试" if body.get("dry_run") else "真实推送",
                                lambda: api_push(body), merchant=merchant))
            elif path == "/api/test/douyin":
                self._json(_run("测试来客凭证", api_test_douyin))
            elif path == "/api/outbox/enqueue":
                merchant = body.get("merchant")
                self._json(_run("拉单入待发队列", lambda: api_outbox_enqueue(body), merchant=merchant))
            elif path == "/api/outbox/test":
                self._json(_run("发送链路测试消息", lambda: api_outbox_test(body)))
            elif path == "/api/outbox/rebind":
                merchant = body.get("merchant")
                self._json(_run("群名重绑定", lambda: api_outbox_rebind(body), merchant=merchant))
            elif path == "/api/outbox/ack":
                self._json(_run("中继回报发送结果", lambda: api_outbox_ack(body)))
            elif path == "/api/outbox/retry":
                self._json(_run("重发待发消息", lambda: api_outbox_retry(body)))
            elif path == "/api/outbox/delete":
                self._json(_run("删除待发消息", lambda: api_outbox_delete(body)))
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except json.JSONDecodeError as e:
            self._json({"ok": False, "error": f"请求体不是合法 JSON: {e}"}, 400)
        except Exception as e:
            logger.error("POST %s error: %s", path, traceback.format_exc(limit=3))
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def main():
    # 前端由宿主机 nginx 静态托管, 容器内没有 web/ 属正常, 只警告不退出
    if not os.path.exists(INDEX_PATH):
        print(f"[admin] 提示: 未找到页面文件 {INDEX_PATH} (前端由 nginx 托管时属正常), /api 不受影响")
    if HOST != "127.0.0.1" and not get_admin_token():
        print("[admin] 警告: 绑定非本机地址但未设置 ADMIN_TOKEN, 接口无鉴权! "
              "强烈建议 ADMIN_HOST=0.0.0.0 时同时设置 ADMIN_TOKEN。")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[admin] 管理后台已启动: http://{HOST}:{PORT}  (Ctrl+C 停止)")
    print(f"[admin] 数据库: data/admin.db | 文件日志: logs/web_admin.log")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[admin] 已停止")


if __name__ == "__main__":
    main()

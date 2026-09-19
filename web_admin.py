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
            if "merchants" in data:
                return f"商户共 {len(data['merchants'])} 个"
            if "logs" in data:
                return f"日志 {data.get('total')} 条"
            if "orders" in data:
                return f"订单 {data.get('total')} 条"
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
    return {"config": _load_cfg()}


def api_save_config(cfg):
    json.dumps(cfg)
    _save_cfg(cfg)
    return {"saved": True}


def api_merchant_save(body):
    m = body.get("merchant") or {}
    if not (m.get("account_id") or "").strip():
        raise ValueError("account_id 不能为空")
    cfg = _load_cfg()
    merchants = cfg.setdefault("merchants", [])
    idx = body.get("index")
    clean = {k: m.get(k) for k in ("account_id", "name", "wecom", "push") if m.get(k) is not None}
    if isinstance(idx, int) and 0 <= idx < len(merchants):
        merchants[idx].update(clean)
    else:
        merchants.append(clean)
    _save_cfg(cfg)
    return {"merchants": merchants}


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


def api_orders_preview(merchant_spec, lookback_minutes=None, limit=20):
    """拉单 -> 解密 -> 存库 -> 生成消息模板(不推送、不写去重状态)。"""
    cfg, m = _merchant_ctx(merchant_spec)
    orders = _fetch_and_store(cfg, m, lookback_minutes)
    messages = sync.build_messages(orders, m["push"])
    brief = [{k: o.get(k) for k in ("order_id", "goods", "amount", "status", "phone", "created_at")}
             for o in orders]
    return {"merchant": m["name"], "account_id": m["account_id"],
            "total": len(orders), "orders": brief,
            "messages": [x["markdown"]["content"] for x in messages][:limit]}


def api_push(body):
    """真实推送: 拉单存库 -> 走去重 -> 推送。dry_run=true 只打印消息不发送。"""
    cfg, m = _merchant_ctx(body.get("merchant"))
    orders = _fetch_and_store(cfg, m, body.get("lookback_minutes"))
    ok = sync.process_merchant(cfg, m, orders, dry_run=bool(body.get("dry_run")))
    return {"ok_push": ok, "fetched": len(orders)}


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
                self._json({"ok": True, "service": "dylk-wecom-admin"})
                return
            if not self._authed(qs):
                self._json({"ok": False, "error": "unauthorized: 缺少或错误的访问令牌(X-Admin-Token)"}, 401)
                return
            if path == "/api/config":
                self._json(_run("查看配置", api_get_config))
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
                    limit=int((qs.get("limit") or ["20"])[0])), merchant=merchant))
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
            else:
                self._json({"ok": False, "error": "not found"}, 404)
        except json.JSONDecodeError as e:
            self._json({"ok": False, "error": f"请求体不是合法 JSON: {e}"}, 400)
        except Exception as e:
            logger.error("POST %s error: %s", path, traceback.format_exc(limit=3))
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def main():
    if not os.path.exists(INDEX_PATH):
        sys.exit(f"找不到页面文件: {INDEX_PATH}")
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

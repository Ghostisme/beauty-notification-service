# -*- coding: utf-8 -*-
"""
SQLite 存储: 订单数据管理 + 运行日志(操作/推送/错误追踪)。
数据库文件: data/admin.db
"""

import datetime as dt
import os
import re
import sqlite3
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "admin.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL,
  merchant_name TEXT,
  order_id TEXT NOT NULL,
  goods TEXT, amount TEXT, status TEXT,
  customer TEXT, phone TEXT, created_at TEXT,
  fetched_at TEXT,
  UNIQUE(account_id, order_id)
);
CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, level TEXT, merchant TEXT,
  action TEXT, ok INTEGER, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_id);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
CREATE INDEX IF NOT EXISTS idx_logs_action ON logs(action);
"""

_phone_re = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def mask_phone(text):
    """日志里手机号脱敏: 138****8000"""
    return _phone_re.sub(lambda m: m.group()[:3] + "****" + m.group()[-4:], str(text))


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with _lock, _conn() as c:
        c.executescript(SCHEMA)


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


# ---------------- 订单数据 ----------------

def upsert_orders(account_id, merchant_name, orders):
    """按 (account_id, order_id) 幂等写入/更新订单快照。"""
    now = _now()
    n = 0
    with _lock, _conn() as c:
        for o in orders:
            if not o.get("order_id"):
                continue
            c.execute(
                """INSERT INTO orders(account_id, merchant_name, order_id, goods, amount,
                                      status, customer, phone, created_at, fetched_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(account_id, order_id) DO UPDATE SET
                     merchant_name=excluded.merchant_name,
                     goods=excluded.goods, amount=excluded.amount, status=excluded.status,
                     customer=excluded.customer, phone=excluded.phone,
                     created_at=excluded.created_at, fetched_at=excluded.fetched_at""",
                (str(account_id), merchant_name, str(o.get("order_id")),
                 str(o.get("goods") or ""), str(o.get("amount") or ""),
                 str(o.get("status") or ""), str(o.get("customer") or ""),
                 str(o.get("phone") or ""), str(o.get("created_at") or ""), now))
            n += 1
    return n


def list_orders(account_id=None, keyword="", page=1, page_size=50):
    conds, params = [], []
    if account_id:
        conds.append("account_id=?")
        params.append(str(account_id))
    if keyword:
        conds.append("(order_id LIKE ? OR goods LIKE ? OR phone LIKE ? OR customer LIKE ? OR merchant_name LIKE ?)")
        params += [f"%{keyword}%"] * 5
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 50)))
    sql = f"SELECT * FROM orders{where}"
    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) AS n FROM ({sql})", params).fetchone()["n"]
        rows = c.execute(sql + " ORDER BY id DESC LIMIT ? OFFSET ?",
                         params + [page_size, (page - 1) * page_size]).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "orders": [dict(r) for r in rows]}


# ---------------- 运行日志 ----------------

def add_log(level, merchant, action, ok, detail=""):
    init()
    with _lock, _conn() as c:
        c.execute("INSERT INTO logs(ts, level, merchant, action, ok, detail) VALUES(?,?,?,?,?,?)",
                  (_now(), level, merchant or "", action, 1 if ok else 0,
                   mask_phone(detail)[:2000]))


def list_logs(merchant=None, action=None, level=None, page=1, page_size=50):
    conds, params = [], []
    if merchant:
        conds.append("merchant=?")
        params.append(merchant)
    if action:
        conds.append("action=?")
        params.append(action)
    if level:
        conds.append("level=?")
        params.append(level)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 50)))
    sql = f"SELECT * FROM logs{where}"
    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) AS n FROM ({sql})", params).fetchone()["n"]
        rows = c.execute(sql + " ORDER BY id DESC LIMIT ? OFFSET ?",
                         params + [page_size, (page - 1) * page_size]).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "logs": [dict(r) for r in rows]}


def stats():
    """概览: 各商户订单数 + 今日日志/错误数, 供监控面板用。"""
    today = _now()[:10]
    with _conn() as c:
        by_merchant = [dict(r) for r in c.execute(
            "SELECT merchant_name, account_id, COUNT(*) AS n, MAX(fetched_at) AS latest FROM orders GROUP BY account_id")]
        logs_today = c.execute("SELECT COUNT(*) AS n FROM logs WHERE ts LIKE ?", (today + "%",)).fetchone()["n"]
        errors_today = c.execute("SELECT COUNT(*) AS n FROM logs WHERE ts LIKE ? AND ok=0", (today + "%",)).fetchone()["n"]
    return {"orders_by_merchant": by_merchant, "logs_today": logs_today, "errors_today": errors_today}

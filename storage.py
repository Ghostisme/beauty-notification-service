# -*- coding: utf-8 -*-
"""
SQLite 存储: 订单数据管理 + 运行日志(操作/推送/错误追踪)。
数据库文件: data/admin.db
"""

import datetime as dt
import hashlib
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

-- 待发队列: 零备案通道。服务器只负责入队, 由 Windows 端 wx_relay.py
-- 用普通微信号(或企业微信客户端)把消息发到指定群, 再回调 ack。
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  merchant TEXT, account_id TEXT,
  channel TEXT DEFAULT 'wechat_group',   -- wechat_group(普通微信群) / other
  target TEXT,                            -- 目标群名称(需与群名完全一致)
  content TEXT NOT NULL,                  -- 纯文本正文
  status TEXT DEFAULT 'pending',          -- pending / sent / failed
  tries INTEGER DEFAULT 0,
  dedup TEXT UNIQUE,                      -- 幂等键, 防重复入队
  err TEXT DEFAULT '',
  created_at TEXT, sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);
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


# ---------------- 待发队列(零备案通道) ----------------

MAX_TRIES = 5


def enqueue_outbox(contents, merchant="", account_id="", channel="wechat_group", target=""):
    """把纯文本消息写入待发队列。

    幂等: 同 (account_id, channel, target, content) 只保留一条 —
    处于 pending/sent 的重复内容直接跳过; 处于 failed 的会被重置为 pending 重试。
    返回本次实际新增(或重置)的条数。
    """
    init()
    now = _now()
    n = 0
    with _lock, _conn() as c:
        for content in contents:
            content = (content or "").strip()
            if not content:
                continue
            dedup = hashlib.sha1(
                f"{account_id}|{channel}|{target}|{content}".encode("utf-8")).hexdigest()
            row = c.execute("SELECT id, status FROM outbox WHERE dedup=?", (dedup,)).fetchone()
            if row:
                if row["status"] in ("pending", "sent"):
                    continue
                c.execute("UPDATE outbox SET status='pending', tries=0, err='', created_at=? WHERE id=?",
                          (now, row["id"]))
            else:
                c.execute(
                    """INSERT INTO outbox(merchant, account_id, channel, target, content,
                                          status, tries, dedup, err, created_at)
                       VALUES(?,?,?,?,?,'pending',0,?,'',?)""",
                    (merchant or "", str(account_id or ""), channel, target or "",
                     content, dedup, now))
            n += 1
    return n


def list_outbox(status=None, merchant=None, page=1, page_size=50):
    conds, params = [], []
    if status:
        conds.append("status=?")
        params.append(status)
    if merchant:
        conds.append("merchant=?")
        params.append(merchant)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 50)))
    sql = f"SELECT * FROM outbox{where}"
    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) AS n FROM ({sql})", params).fetchone()["n"]
        rows = c.execute(sql + " ORDER BY id ASC LIMIT ? OFFSET ?",
                         params + [page_size, (page - 1) * page_size]).fetchall()
    return {"total": total, "page": page, "page_size": page_size,
            "items": [dict(r) for r in rows]}


def ack_outbox(ids, ok, err=""):
    """中继回报结果: ok=True 标记 sent; ok=False 累加重试次数, 超过 MAX_TRIES 标记 failed。"""
    init()
    now = _now()
    ids = [int(i) for i in (ids or [])]
    if not ids:
        return 0
    with _lock, _conn() as c:
        n = 0
        for i in ids:
            if ok:
                cur = c.execute(
                    "UPDATE outbox SET status='sent', sent_at=?, tries=tries+1, err='' WHERE id=?",
                    (now, i))
            else:
                cur = c.execute(
                    """UPDATE outbox SET tries=tries+1, err=?,
                         status=CASE WHEN tries+1>=? THEN 'failed' ELSE 'pending' END
                       WHERE id=?""",
                    (str(err)[:500], MAX_TRIES, i))
            n += cur.rowcount
    return n


def retry_outbox(ids):
    """把 sent/failed 的消息重新置为 pending(手工重发用)。"""
    init()
    ids = [int(i) for i in (ids or [])]
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with _lock, _conn() as c:
        cur = c.execute(
            f"UPDATE outbox SET status='pending', tries=0, err='' WHERE id IN ({marks})", ids)
        return cur.rowcount


def delete_outbox(ids):
    init()
    ids = [int(i) for i in (ids or [])]
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with _lock, _conn() as c:
        return c.execute(f"DELETE FROM outbox WHERE id IN ({marks})", ids).rowcount


def outbox_stats():
    init()
    with _conn() as c:
        rows = c.execute("SELECT status, COUNT(*) AS n FROM outbox GROUP BY status").fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    counts["pending"] = counts.get("pending", 0)
    return counts


def pending_targets(merchant=None):
    """按群名统计还没发出去的条数(pending/failed)。用于「群改名后要不要重绑定」的判断。"""
    init()
    conds = ["status IN ('pending','failed')"]
    params = []
    if merchant:
        conds.append("merchant=?")
        params.append(merchant)
    sql = ("SELECT target, status, COUNT(*) AS n FROM outbox WHERE "
           + " AND ".join(conds) + " GROUP BY target, status ORDER BY target")
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    out = {}
    for r in rows:
        item = out.setdefault(r["target"] or "", {"pending": 0, "failed": 0, "total": 0})
        item[r["status"]] = r["n"]
        item["total"] += r["n"]
    return out


def rebind_outbox_target(merchant, new_target, old_target=None, retry_failed=True):
    """群改名后「重新绑定」: 把某商户待发队列里指向旧群名的消息改指到新群名。

    为什么需要: 队列里的 target 是**入队那一刻写死的群名**。群一旦被改名(通常由企微
    群主在手机端改), 存量消息会一直发不出去(中继报「找不到群」)。改完配置里的群名字段
    后调用本函数, 存量消息就跟上新群名, 不用逐条删掉重入队。

    old_target 传 None 表示"该商户所有指向其它群名的行都改"(本项目一个商户只绑一个群, 安全)。
    retry_failed=True 时, 已 failed 的行会被重置为 pending 并清零重试次数, 中继下一轮就会重发。

    返回 {"updated": n, "merged": n, "old_targets": [...], "to": 新群名}
    """
    init()
    new_target = (new_target or "").strip()
    if not new_target:
        raise ValueError("新群名不能为空")

    conds = ["merchant=?", "target<>?", "status IN ('pending','failed')"]
    params = [merchant or "", new_target]
    if old_target is not None:
        conds.append("target=?")
        params.append(old_target)

    with _lock, _conn() as c:
        rows = c.execute(f"SELECT * FROM outbox WHERE {' AND '.join(conds)}", params).fetchall()
        updated = merged = 0
        olds = []
        for r in rows:
            olds.append(r["target"] or "")
            new_dedup = hashlib.sha1(
                f"{r['account_id']}|{r['channel']}|{new_target}|{r['content']}"
                .encode("utf-8")).hexdigest()
            status = "pending" if (retry_failed and r["status"] == "failed") else r["status"]
            try:
                c.execute(
                    """UPDATE outbox SET target=?, dedup=?, status=?, tries=0, err=''
                       WHERE id=?""", (new_target, new_dedup, status, r["id"]))
                updated += 1
            except sqlite3.IntegrityError:
                # 新群名下已经有内容一模一样的记录 → 这条只是历史遗留的重复, 合并掉
                c.execute("DELETE FROM outbox WHERE id=?", (r["id"],))
                merged += 1
    return {"updated": updated, "merged": merged,
            "old_targets": sorted(set(olds)), "to": new_target}


def rename_outbox_merchant(old_name, new_name):
    """商户改名后, 把队列里归属该商户的历史记录一起改名, 免得在界面上"消失"。"""
    init()
    old_name, new_name = (old_name or "").strip(), (new_name or "").strip()
    if not old_name or not new_name or old_name == new_name:
        return 0
    with _lock, _conn() as c:
        return c.execute("UPDATE outbox SET merchant=? WHERE merchant=?",
                         (new_name, old_name)).rowcount


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
    return {"orders_by_merchant": by_merchant, "logs_today": logs_today,
            "errors_today": errors_today, "outbox": outbox_stats()}

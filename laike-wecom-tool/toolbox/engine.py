import json
import secrets
import threading
import time
import uuid

import requests

from .db import dumps
from .defaults import EVENT_NAMES, ORDER_STATUSES
from .domain import epoch, error_text, event_key, normalize_order, public_phone, render, text
from .douyin import DouyinClient


class Conflict(ValueError):
    pass


class Engine:
    def __init__(self, db, client=None):
        self.db = db
        self.client = client or DouyinClient(db)
        self.stop_event = threading.Event()
        self.sync_lock = threading.Lock()
        self.last_tick = 0
        self.next_sync = 0
        self.next_dispatch = 0
        self.started_at = time.time()
        self.thread = None
        self.sync_thread = None
        self.dispatch_thread = None
        self.launch_lock = threading.Lock()
        self.http = requests.Session()

    def _enterprise(self, c, account_id):
        row = c.execute("SELECT * FROM enterprises WHERE account_id=?", (str(account_id),)).fetchone()
        if not row:
            raise ValueError("商户账号尚未绑定，请先在企业与门店中添加企业")
        return dict(row)

    def _emit(self, c, enterprise, category, name, payload, identity="", now=None):
        now = now or time.time()
        record_id = text(payload.get("record_id"), 120)
        key = event_key(enterprise["account_id"], category, record_id, identity)
        template_row = c.execute("SELECT * FROM templates WHERE kind=?", (category,)).fetchone()
        if not template_row:
            raise ValueError("不支持的通知类型")
        template = dict(template_row)
        payload = {**payload, "event_name": name}
        event_time = epoch(payload.get("event_time"), now)
        if event_time > now + 300:
            raise ValueError("业务事件时间不能晚于当前时间五分钟以上")
        unique = c.execute("INSERT OR IGNORE INTO dedup_keys VALUES (?,?)", (key, now))
        if not unique.rowcount:
            return {"duplicate": True, "queued": 0}
        inserted = c.execute("INSERT INTO events(event_key,enterprise_id,category,event_name,record_id,event_time,payload,created_at) VALUES (?,?,?,?,?,?,?,?)",
                             (key, enterprise["id"], category, name, record_id, event_time, dumps(payload), now))
        event_id = inserted.lastrowid
        store = c.execute("SELECT * FROM stores WHERE enterprise_id=? AND poi_id=?",
                          (enterprise["id"], str(payload.get("poi_id") or ""))).fetchone()
        status, error = "pending", ""
        max_age = json.loads(c.execute("SELECT value FROM settings WHERE key='scheduler'").fetchone()[0])["max_age_minutes"]
        if now - event_time > max_age * 60:
            status = "skipped_old"
        elif not template["enabled"]:
            status = "muted"
        elif not enterprise["enabled"] or (store and not store["enabled"]):
            status = "blocked"
        elif not store or not store["group_id"] or not store["group_name"]:
            status, error = "unrouted", "未找到本企业内门店的完整群绑定，请手动分配"
        body = render(template, payload, enterprise["name"], store["name"] if store else "")
        msg = c.execute("INSERT INTO messages(event_id,enterprise_id,store_id,category,group_id,group_name,body,status,last_error,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (event_id, enterprise["id"], store["id"] if store else None, category,
                         store["group_id"] if store else "", store["group_name"] if store else "",
                         body, status, error, now, now))
        return {"duplicate": False, "queued": int(status == "pending"), "message_id": msg.lastrowid, "status": status}

    def ingest_order(self, account_id, raw, now=None):
        now = now or time.time()
        merchant = raw.get("merchant_info") if isinstance(raw, dict) else None
        if isinstance(merchant, dict) and merchant.get("account_id") and str(merchant["account_id"]) != str(account_id):
            raise ValueError("订单中的商户账号与接入企业不一致")
        order = normalize_order(raw, self.db.settings("douyin")["amount_unit"])
        rules = self.db.settings("notifications")
        results = []
        with self.db.connect(write=True) as c:
            enterprise = self._enterprise(c, account_id)
            old_row = c.execute("SELECT payload FROM snapshots WHERE enterprise_id=? AND record_type='order' AND record_id=?",
                                (enterprise["id"], order["record_id"])).fetchone()
            previous = json.loads(old_row[0]) if old_row else None
            if previous and order.get("updated_time") and previous.get("updated_time") and order["updated_time"] < previous["updated_time"]:
                return {"record_id": order["record_id"], "queued": 0, "notifications": [], "ignored": "older_snapshot"}
            notified = previous.get("new_notified", False) if previous else False
            paid = order["status_code"] in ("200", "201", "150")
            if rules["order_trigger"] == "created" or paid:
                if not notified:
                    payload = {**order, "event_time": order.get("paid_time") if rules["order_trigger"] == "paid" else order.get("created_time")}
                    payload["event_time"] = payload["event_time"] or order.get("created_time") or now
                    results.append(self._emit(c, enterprise, "new_order", "新订单通知", payload, now=now))
                    notified = True
            if previous:
                old_code = previous.get("status_code", "")
                new_code = order["status_code"]
                event = "canceled" if new_code == "101" else ("paid" if paid and old_code not in ("200", "201", "150") else "")
                suppress_paid = event == "paid" and rules["order_trigger"] == "paid"
                if old_code != new_code and event in rules["status_events"] and not suppress_paid:
                    payload = {**order, "previous_status": ORDER_STATUSES.get(old_code, old_code), "current_status": order["status"],
                               "event_time": order.get("updated_time") or now}
                    results.append(self._emit(c, enterprise, "status_change", EVENT_NAMES[event], payload,
                                              f"order:{event}:{order.get('updated_time') or new_code}", now))
                old_certs = previous.get("certificates", {})
                for cid, cert in order["certificates"].items():
                    old_status = old_certs.get(cid, {}).get("status", "")
                    if old_status == cert["status"]:
                        continue
                    subtype = next((name for name, rule in (("verified", "verified_statuses"), ("refunded", "refunded_statuses"),
                                                           ("refunding", "refunding_statuses"))
                                    if str(cert["status"]) in [str(v) for v in rules[rule]]), "")
                    if subtype not in rules["status_events"]:
                        continue
                    current = {"verified": "已核销", "refunded": "已退款", "refunding": "退款中"}[subtype]
                    payload = {**order, "certificate_id": cid, "event_time": cert["time"] or order.get("updated_time") or now,
                               "poi_id": cert["poi_id"] or order["poi_id"], "refund_amount": cert["refund_amount"],
                               "previous_status": {"401": "已核销", "301": "已退款", "300": "退款中"}.get(old_status, "待使用"),
                               "current_status": current}
                    results.append(self._emit(c, enterprise, "status_change", EVENT_NAMES[subtype], payload,
                                              f"certificate:{cid}:{subtype}:{cert['time'] or cert['status']}", now))
            # 首次接入时只建立券状态基线，不能把已经核销的历史券当成刚发生的核销。
            order["new_notified"] = notified
            c.execute("INSERT INTO snapshots VALUES (?,'order',?,?,?) ON CONFLICT(enterprise_id,record_type,record_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                      (enterprise["id"], order["record_id"], dumps(order), now))
        return {"record_id": order["record_id"], "queued": sum(r["queued"] for r in results), "notifications": results}

    def ingest_event(self, raw, now=None):
        now = now or time.time()
        if not isinstance(raw, dict):
            raise ValueError("事件必须是对象")
        account_id = text(raw.get("account_id"), 120)
        category = raw.get("type")
        if category == "order":
            return self.ingest_order(account_id, raw.get("data"), now)
        if category not in ("new_lead", "status_change"):
            raise ValueError("type 仅支持 order、new_lead、status_change；留资必须来自独立留资记录")
        source = raw.get("data")
        if not isinstance(source, dict):
            raise ValueError("data 必须是对象")
        record_id = text(raw.get("record_id") or source.get("record_id"), 120)
        if not account_id or not record_id:
            raise ValueError("account_id 和 record_id 必填")
        subtype = text(raw.get("event"), 40)
        if category == "status_change" and subtype not in EVENT_NAMES:
            raise ValueError("状态事件需要 event：paid/verified/refunding/refunded/canceled")
        payload = {k: text(source.get(k), 1000 if k == "remark" else 500) for k in
                   ("poi_name", "customer", "goods", "quantity", "amount", "status", "intent", "source", "remark",
                    "previous_status", "current_status", "refund_amount", "certificate_id")}
        payload.update({"record_id": record_id, "poi_id": text(raw.get("poi_id") or source.get("poi_id"), 120),
                        "phone": public_phone(source.get("phone")), "created_time": epoch(source.get("created_time")),
                        "event_time": epoch(raw.get("event_time"), now)})
        identity = "lead" if category == "new_lead" else text(raw.get("event_id"), 200)
        if category == "status_change" and not identity:
            raise ValueError("状态事件必须提供稳定的 event_id，用于重复请求去重")
        with self.db.connect(write=True) as c:
            enterprise = self._enterprise(c, account_id)
            rules = json.loads(c.execute("SELECT value FROM settings WHERE key='notifications'").fetchone()[0])
            if category == "status_change" and subtype not in rules["status_events"]:
                return {"ignored": True, "queued": 0, "reason": "该状态事件未启用"}
            result = self._emit(c, enterprise, category, "新留资通知" if category == "new_lead" else EVENT_NAMES[subtype], payload, identity, now)
            if category == "new_lead":
                c.execute("INSERT INTO snapshots VALUES (?,'lead',?,?,?) ON CONFLICT(enterprise_id,record_type,record_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                          (enterprise["id"], record_id, dumps(payload), now))
            return result

    def recover(self):
        """发送超时只转人工核实；进程恢复不盲目重发可能已经发出的消息。"""
        now = time.time()
        with self.db.connect(write=True) as c:
            count = c.execute("UPDATE messages SET status='uncertain',last_error='发送回执超时，请核实群内消息后处理',lease_until=NULL,updated_at=?,version=version+1 WHERE status IN ('sending','waiting_receipt') AND lease_until<?", (now, now)).rowcount
            c.execute("UPDATE attempts SET outcome='uncertain',finished_at=?,detail='发送回执超时' WHERE outcome IN ('sending','waiting_receipt') AND lease_token IN (SELECT lease_token FROM messages WHERE status='uncertain')", (now,))
        return count

    def claim(self, worker_id, groups=None):
        if not self.db.settings("notifications")["delivery_enabled"]:
            return None
        cfg = self.db.settings("channel")
        now = time.time()
        allowed = None if groups is None else set(str(v) for v in groups)
        with self.db.connect(write=True) as c:
            scope, args = "", [now]
            if allowed is not None:
                if not allowed:
                    return None
                scope = " AND m.group_id IN (" + ",".join("?" for _ in allowed) + ")"
                args.extend(sorted(allowed))
            rows = c.execute("SELECT m.*,evt.event_key AS dedup_key,s.enabled AS store_enabled,s.group_id AS current_group,s.group_name AS current_group_name,e.enabled AS enterprise_enabled,t.enabled AS template_enabled FROM messages m JOIN events evt ON evt.id=m.event_id LEFT JOIN stores s ON s.id=m.store_id JOIN enterprises e ON e.id=m.enterprise_id JOIN templates t ON t.kind=m.category WHERE m.status='pending' AND m.next_attempt<=?" + scope + " ORDER BY m.id LIMIT 100", args).fetchall()
            for row in rows:
                m = dict(row)
                if allowed is not None and m["group_id"] not in allowed:
                    continue
                if not m["enterprise_enabled"] or not m["store_enabled"]:
                    c.execute("UPDATE messages SET status='blocked',updated_at=?,version=version+1 WHERE id=?", (now, m["id"]))
                    continue
                if not m["template_enabled"]:
                    c.execute("UPDATE messages SET status='muted',updated_at=?,version=version+1 WHERE id=?", (now, m["id"]))
                    continue
                if m["group_id"] != m["current_group"] or m["group_name"] != m["current_group_name"]:
                    c.execute("UPDATE messages SET status='unrouted',last_error='门店接收群已变更，请重新分配',updated_at=?,version=version+1 WHERE id=?", (now, m["id"]))
                    continue
                lease = uuid.uuid4().hex
                c.execute("UPDATE messages SET status='sending',lease_token=?,lease_until=?,worker_id=?,attempts=attempts+1,updated_at=?,version=version+1 WHERE id=?", (lease, now + cfg["lease_seconds"], worker_id, now, m["id"]))
                c.execute("INSERT INTO attempts(message_id,number,lease_token,started_at) VALUES (?,?,?,?)", (m["id"], m["attempts"] + 1, lease, now))
                return {"id": m["id"], "idempotency_key": f"laike-{m['dedup_key']}-r{m['retry_generation']}", "lease_token": lease,
                        "lease_until": now + cfg["lease_seconds"], "group_id": m["group_id"], "group_name": m["group_name"],
                        "text": m["body"], "category": m["category"], "attempt": m["attempts"] + 1,
                        "is_test": bool(m["is_test"])}
        return None

    def finish(self, message_id, lease, outcome, detail="", remote_id="", group_id=None, receipt=None):
        if outcome not in ("sent", "failed", "uncertain", "accepted"):
            raise ValueError("发送结果必须是 sent/failed/uncertain/accepted")
        cfg, now = self.db.settings("channel"), time.time()
        with self.db.connect(write=True) as c:
            row = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            if not row or not secrets.compare_digest(row["lease_token"] or "", str(lease or "")):
                raise Conflict("发送回执已过期或不属于当前发送尝试")
            if row["status"] == "sent" and outcome == "sent":
                return {"status": "sent", "duplicate_receipt": True}
            if row["status"] not in ("sending", "waiting_receipt", "uncertain"):
                raise Conflict("这条通知已由其他操作处理")
            if group_id is not None and str(group_id) != row["group_id"]:
                outcome, detail = "uncertain", "发送端回报的接收群与任务不一致，请人工核实"
            status = {"accepted": "waiting_receipt"}.get(outcome, outcome)
            next_attempt = 0
            # failed 必须表示发送端确认没有发送；网络超时使用 uncertain。
            if outcome == "failed" and row["attempts"] < cfg["max_attempts"]:
                status = "pending"
                next_attempt = now + min(900, 15 * 2 ** (row["attempts"] - 1))
            deadline = now + cfg["lease_seconds"] if outcome == "accepted" else None
            detail = error_text(detail, (self.db.secret("http_token"), self.db.secret("relay_token")))
            c.execute("UPDATE messages SET status=?,next_attempt=?,lease_until=?,remote_id=?,last_error=?,result_source=?,sent_at=?,updated_at=?,version=version+1 WHERE id=?",
                      (status, next_attempt, deadline, text(remote_id, 200), detail, "sender" if outcome == "sent" else "",
                       now if outcome == "sent" else None, now, message_id))
            c.execute("UPDATE attempts SET outcome=?,finished_at=?,detail=?,receipt=? WHERE lease_token=?",
                      ("waiting_receipt" if outcome == "accepted" else outcome, None if outcome == "accepted" else now,
                       detail, dumps(receipt or {}), lease))
            return {"status": status, "next_attempt": next_attempt}

    def dispatch_once(self):
        cfg = self.db.settings("channel")
        if cfg["mode"] != "http" or not cfg["http_url"]:
            return None
        job = self.claim("http-bridge")
        if not job:
            return None
        token = self.db.secret("http_token")
        headers = {"Idempotency-Key": job["idempotency_key"]}
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            r = self.http.post(cfg["http_url"], json=job, headers=headers, timeout=(5, cfg["timeout_seconds"]), allow_redirects=False)
            # 即使 HTTP 报错，远端也可能已经发送；只有明确的业务回执才可判定失败。
            try:
                result = r.json()
            except ValueError:
                result = {}
            state = result.get("status") if isinstance(result, dict) else None
            if state not in ("sent", "failed", "accepted", "uncertain"):
                state = "uncertain"
                result = {"message": f"发送工具返回 HTTP {r.status_code}，未提供明确发送回执"}
            elif state == "sent" and not result.get("group_id"):
                state = "uncertain"
                result["message"] = "发送工具未回报实际接收群，请人工核实"
            return self.finish(job["id"], job["lease_token"], state,
                               result.get("message", ""), result.get("message_id", ""),
                               result.get("group_id"), {"http_status": r.status_code, "status": state})
        except requests.RequestException as e:
            return self.finish(job["id"], job["lease_token"], "uncertain", error_text(e, (token,)))

    def run_sync(self, trigger="manual"):
        if not self.sync_lock.acquire(blocking=False):
            raise Conflict("已有同步任务正在运行")
        now = time.time()
        cfg = self.db.settings("scheduler")
        with self.db.connect(write=True) as c:
            run_id = c.execute("INSERT INTO task_runs(trigger,status,started_at) VALUES (?,'running',?)", (trigger, now)).lastrowid
        details, orders_count, queued, errors = [], 0, 0, 0
        try:
            enterprises = self.db.rows("SELECT * FROM enterprises WHERE enabled=1 ORDER BY id")
            for enterprise in enterprises:
                start = enterprise["sync_cursor"] - 180 if enterprise["sync_cursor"] else now - cfg["lookback_minutes"] * 60
                # 拆小时间窗。服务器长时间停机后逐轮追赶，成功后才推进该企业游标。
                end = min(now - 3, start + 86400)
                entry = {"enterprise": enterprise["name"], "orders": 0, "queued": 0}
                try:
                    batch = []
                    warning = ""
                    for raw in self.client.orders(enterprise["account_id"], start, end, cfg["max_pages"]):
                        if self.stop_event.is_set():
                            raise RuntimeError("服务停止，本企业同步游标未推进")
                        batch.append(raw)
                        if len(batch) >= 100:
                            batch, warning = self.client.decrypt_orders(batch, enterprise["account_id"])
                            for item in batch:
                                result = self.ingest_order(enterprise["account_id"], item)
                                entry["orders"] += 1
                                entry["queued"] += result["queued"]
                            batch = []
                    if batch:
                        batch, warning = self.client.decrypt_orders(batch, enterprise["account_id"])
                        for item in batch:
                            result = self.ingest_order(enterprise["account_id"], item)
                            entry["orders"] += 1
                            entry["queued"] += result["queued"]
                    with self.db.connect(write=True) as c:
                        c.execute("UPDATE enterprises SET sync_cursor=?,last_sync=?,last_error=? WHERE id=?", (end, time.time(), warning, enterprise["id"]))
                    if warning:
                        entry["warning"] = warning
                except Exception as e:
                    errors += 1
                    entry["error"] = error_text(e, (self.db.secret("douyin_secret"),))
                    with self.db.connect(write=True) as c:
                        c.execute("UPDATE enterprises SET last_error=? WHERE id=?", (entry["error"], enterprise["id"]))
                orders_count += entry["orders"]
                queued += entry["queued"]
                details.append(entry)
            status = "partial" if errors and errors < len(details) else ("failed" if errors else "success")
            with self.db.connect(write=True) as c:
                c.execute("UPDATE task_runs SET status=?,finished_at=?,orders=?,queued=?,errors=?,details=? WHERE id=?",
                          (status, time.time(), orders_count, queued, errors, dumps(details), run_id))
            return {"id": run_id, "status": status, "orders": orders_count, "queued": queued, "errors": errors, "details": details}
        except BaseException:
            with self.db.connect(write=True) as c:
                c.execute("UPDATE task_runs SET status='failed',finished_at=?,errors=errors+1 WHERE id=?", (time.time(), run_id))
            raise
        finally:
            self.sync_lock.release()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        with self.db.connect(write=True) as c:
            c.execute("UPDATE task_runs SET status='interrupted',finished_at=? WHERE status='running'", (time.time(),))
        self.thread = threading.Thread(target=self._loop, name="laike-scheduler", daemon=True)
        self.thread.start()

    def launch_sync(self, trigger="manual"):
        with self.launch_lock:
            if self.sync_lock.locked() or (self.sync_thread and self.sync_thread.is_alive()):
                raise Conflict("已有同步任务正在运行")
            def work():
                try:
                    self.run_sync(trigger)
                except Conflict:
                    pass
                except Exception as e:
                    self.db.audit("同步任务异常", detail=error_text(e, (self.db.secret("douyin_secret"),)))
            self.sync_thread = threading.Thread(target=work, name="laike-sync", daemon=True)
            self.sync_thread.start()

    def _loop(self):
        self.next_sync = time.time() + 5
        next_maintenance = 0
        next_cleanup = time.time() + 60
        while not self.stop_event.is_set():
            self.last_tick = time.time()
            if self.last_tick >= next_maintenance:
                try:
                    self.recover()
                except Exception as e:
                    self.db.audit("任务维护异常", detail=error_text(e))
                next_maintenance = self.last_tick + 15
            scheduler = self.db.settings("scheduler")
            if self.last_tick >= next_cleanup:
                try:
                    self.db.cleanup()
                except Exception as e:
                    self.db.audit("历史记录清理异常", detail=error_text(e))
                next_cleanup = self.last_tick + 86400
            if scheduler["enabled"] and self.last_tick >= self.next_sync:
                try:
                    self.launch_sync("scheduled")
                except Conflict:
                    pass
                except Exception as e:
                    self.db.audit("自动同步异常", detail=error_text(e))
                self.next_sync = time.time() + scheduler["interval_seconds"]
            if self.last_tick >= self.next_dispatch:
                if not self.dispatch_thread or not self.dispatch_thread.is_alive():
                    def dispatch():
                        try:
                            self.dispatch_once()
                        except Exception as e:
                            self.db.audit("发送调度异常", detail=error_text(e))
                    self.dispatch_thread = threading.Thread(target=dispatch, name="laike-dispatch", daemon=True)
                    self.dispatch_thread.start()
                self.next_dispatch = time.time() + self.db.settings("channel")["interval_seconds"]
            self.stop_event.wait(1)

    def stop(self):
        self.stop_event.set()
        for thread in (self.thread, self.sync_thread, self.dispatch_thread):
            if thread and thread is not threading.current_thread():
                thread.join(timeout=25)

    def manual_action(self, message_id, action, data):
        now = time.time()
        with self.db.connect(write=True) as c:
            row = c.execute("SELECT m.*,e.payload,e.record_id FROM messages m JOIN events e ON e.id=m.event_id WHERE m.id=?", (message_id,)).fetchone()
            if not row:
                raise ValueError("通知不存在")
            row = dict(row)
            if int(data.get("version", -1)) != row["version"]:
                raise Conflict("通知已被其他任务更新，请刷新后操作")
            if row["status"] in ("sending", "waiting_receipt"):
                raise Conflict("正在发送或等待回执，请先等待结果或超时后处理")
            if action in ("retry", "route") and row["status"] == "uncertain" and not text(data.get("note"), 500):
                raise ValueError("请先核实群内未发送，并填写核实说明再补发")
            if action == "retry":
                if row["status"] in ("sent", "canceled"):
                    raise Conflict("已发送或已取消的通知不能直接重试")
                store = c.execute("SELECT s.*,e.enabled AS enterprise_enabled FROM stores s JOIN enterprises e ON e.id=s.enterprise_id WHERE s.id=?", (row["store_id"],)).fetchone()
                if not store or not store["enabled"] or not store["enterprise_enabled"] or not store["group_id"]:
                    raise ValueError("请先启用企业、门店并完成群绑定")
                template = c.execute("SELECT enabled FROM templates WHERE kind=?", (row["category"],)).fetchone()
                if not template[0]:
                    raise ValueError("请先开启对应通知模板")
                c.execute("UPDATE messages SET status='pending',next_attempt=0,lease_token=NULL,lease_until=NULL,last_error='',group_id=?,group_name=?,updated_at=?,version=version+1,retry_generation=retry_generation+1 WHERE id=?",
                          (store["group_id"], store["group_name"], now, message_id))
            elif action == "cancel":
                if row["status"] == "sent":
                    raise Conflict("已发送的消息不能撤销")
                c.execute("UPDATE messages SET status='canceled',updated_at=?,version=version+1 WHERE id=?", (now, message_id))
            elif action == "mark_sent":
                note = text(data.get("note"), 500)
                if not note:
                    raise ValueError("请填写人工核实说明")
                c.execute("UPDATE messages SET status='sent',result_source='manual',last_error=?,sent_at=?,updated_at=?,version=version+1 WHERE id=?", (note, now, now, message_id))
            elif action == "edit":
                body = text(data.get("body"), 12000)
                if not body or row["status"] in ("sent", "canceled"):
                    raise ValueError("仅可编辑尚未发送、未取消的通知")
                c.execute("UPDATE messages SET body=?,updated_at=?,version=version+1 WHERE id=?", (body, now, message_id))
            elif action == "route":
                if row["status"] in ("sent", "canceled"):
                    raise ValueError("已发送或取消的通知不能重新分配")
                store = c.execute("SELECT * FROM stores WHERE id=? AND enterprise_id=?", (data.get("store_id"), row["enterprise_id"])).fetchone()
                if not store or not store["enabled"] or not store["group_id"] or not store["group_name"]:
                    raise ValueError("只能分配到本企业内已启用且群绑定完整的门店")
                enterprise = c.execute("SELECT * FROM enterprises WHERE id=?", (row["enterprise_id"],)).fetchone()
                template = dict(c.execute("SELECT * FROM templates WHERE kind=?", (row["category"],)).fetchone())
                body = render(template, json.loads(row["payload"]), enterprise["name"], store["name"])
                status = "pending" if enterprise["enabled"] and template["enabled"] else "blocked"
                c.execute("UPDATE messages SET store_id=?,group_id=?,group_name=?,body=?,status=?,next_attempt=0,lease_token=NULL,lease_until=NULL,last_error='',updated_at=?,version=version+1,retry_generation=retry_generation+1 WHERE id=?",
                          (store["id"], store["group_id"], store["group_name"], body, status, now, message_id))
            else:
                raise ValueError("不支持的操作")
            self.db.audit(action, message_id, text(data.get("note"), 500), c)
        return self.message_detail(message_id)

    def message_detail(self, message_id):
        row = self.db.one("SELECT m.*,e.event_name,e.record_id,e.event_time,e.payload,n.name AS enterprise_name,s.name AS store_name FROM messages m JOIN events e ON e.id=m.event_id JOIN enterprises n ON n.id=m.enterprise_id LEFT JOIN stores s ON s.id=m.store_id WHERE m.id=?", (message_id,))
        if not row:
            raise ValueError("通知不存在")
        row.pop("lease_token", None)
        row["payload"] = json.loads(row["payload"])
        row["attempt_history"] = self.db.rows("SELECT number,started_at,finished_at,outcome,detail,receipt FROM attempts WHERE message_id=? ORDER BY id DESC", (message_id,))
        return row

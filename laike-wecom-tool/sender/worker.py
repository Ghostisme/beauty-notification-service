import json
import contextlib
import logging
import logging.handlers
import sqlite3
import threading
import time
from pathlib import Path

import requests

from .desktop import BeforeSendError, UncertainSendError, WindowsDesktop


class Ledger:
    """本机发送账本：发送前持久化、回执失败可重报、同一任务不会盲目重发。"""
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS deliveries (key TEXT PRIMARY KEY,group_id TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL DEFAULT '{}',pending_ack INTEGER NOT NULL DEFAULT 0,updated_at REAL NOT NULL)")
    @contextlib.contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=10);c.row_factory=sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:c.close()
    def get(self,key):
        with self.connect() as c:
            row=c.execute("SELECT * FROM deliveries WHERE key=?",(key,)).fetchone();return dict(row) if row else None
    def update(self,key,group_id,state,receipt=None,pending=False):
        with self.connect() as c:
            c.execute("INSERT INTO deliveries VALUES (?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET group_id=excluded.group_id,state=excluded.state,receipt=excluded.receipt,pending_ack=excluded.pending_ack,updated_at=excluded.updated_at",
                      (key,group_id,state,json.dumps(receipt or {},ensure_ascii=False),int(pending),time.time()))
    def pending(self):
        with self.connect() as c:return [dict(r) for r in c.execute("SELECT * FROM deliveries WHERE pending_ack=1 ORDER BY updated_at LIMIT 50")]
    def acknowledged(self,key):
        with self.connect() as c:c.execute("UPDATE deliveries SET pending_ack=0 WHERE key=?",(key,))


class Worker:
    def __init__(self,config,desktop=None):
        self.config=config
        self.base=config["server"].rstrip("/")
        self.token=config["token"]
        self.id=config.get("worker_id","windows-wecom-1")
        self.stop=threading.Event()
        self.data=Path(config.get("data_dir","sender-data"));self.data.mkdir(parents=True,exist_ok=True)
        self.ledger=Ledger(self.data/"deliveries.db")
        profile_path=Path(config.get("profile","sender-data/desktop-profile.json"))
        self.desktop=desktop or WindowsDesktop(json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {})
        self.groups=[]
        self.readiness_detail="等待检查"
        self.groups_at=0
        self.groups_lock=threading.Lock()
        self.network=threading.local()
        self.logger=logging.getLogger("laike-sender")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler=logging.handlers.RotatingFileHandler(self.data/"sender.log",maxBytes=1024*1024,backupCount=3,encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.logger.addHandler(handler);self.logger.addHandler(logging.StreamHandler())

    def request(self,path,body=None):
        headers={"Authorization":"Bearer "+self.token}
        if not getattr(self.network,"session",None):self.network.session=requests.Session()
        if body is None:r=self.network.session.get(self.base+path,headers=headers,timeout=(5,15))
        else:r=self.network.session.post(self.base+path,headers=headers,json=body,timeout=(5,15))
        r.raise_for_status();return r.json()

    def heartbeat(self):
        with self.groups_lock:
            if time.monotonic()-self.groups_at>=60 or not self.groups_at:
                self.groups=self.request("/api/relay/groups")["items"]
                self.groups_at=time.monotonic()
        allow=self.config.get("group_ids")
        names=self.config.get("group_names")
        groups=[g["group_id"] for g in self.groups
                if (allow is None or g["group_id"] in allow) and (names is None or g["group_name"] in names)]
        ready,detail=self.desktop.ready()
        if not groups:
            ready=False
            detail="没有匹配的接收群配置，请在后台绑定本发送端负责的门店群"
        self.readiness_detail=detail
        self.request("/api/relay/heartbeat",{"worker_id":self.id,"label":self.config.get("label","Windows 企微发送端"),"ready":ready,"detail":detail,"groups":groups})
        return ready

    def heartbeat_loop(self):
        while not self.stop.is_set():
            try:self.heartbeat()
            except Exception as e:self.logger.warning("心跳暂时失败：%s",type(e).__name__)
            self.stop.wait(15)

    def flush_receipts(self):
        for row in self.ledger.pending():
            try:
                self.request("/api/relay/result",json.loads(row["receipt"]))
                self.ledger.acknowledged(row["key"])
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in (400,409):
                    # 云端已人工处理或换了新的发送尝试。保留本地账本，不覆盖云端的新操作。
                    self.ledger.acknowledged(row["key"])
                    self.logger.warning("旧回执已停止重报，请在后台核实：%s",row["key"])
                else:raise

    def process(self,job):
        key,group=job["idempotency_key"],job["group_id"]
        prior=self.ledger.get(key)
        result=None
        if prior and prior["state"]=="sent" and prior["group_id"]==group:
            result={"status":"sent","detail":"本机账本已确认此任务发送成功，重报回执","group_id":group}
        elif prior and prior["state"] in ("sending","uncertain"):
            result={"status":"uncertain","detail":"本机账本记录上次发送结果不明，请先人工核实","group_id":group}
        elif prior and prior["state"]=="sent":
            result={"status":"uncertain","detail":"本机已向原绑定群发送过该通知，当前群绑定已变化，请人工核实","group_id":prior["group_id"]}
        else:
            try:
                self.ledger.update(key,group,"prepared")
                result=self.desktop.send(job,lambda:self.ledger.update(key,group,"sending"))
            except BeforeSendError as e:result={"status":"failed","detail":str(e),"group_id":group}
            except UncertainSendError as e:result={"status":"uncertain","detail":str(e),"group_id":group}
            except Exception as e:
                row=self.ledger.get(key)
                result={"status":"uncertain" if row and row["state"]=="sending" else "failed",
                        "detail":"发送端操作中断："+type(e).__name__,"group_id":group}
        receipt={"message_id":job["id"],"lease_token":job["lease_token"],**result,"remote_id":"windows-ledger:"+key}
        self.ledger.update(key,group,result["status"],receipt,pending=True)
        self.logger.info("任务 %s：%s",job["id"],result["status"])
        self.flush_receipts()
        return result

    def run(self,once=False):
        thread=threading.Thread(target=self.heartbeat_loop,daemon=True,name="sender-heartbeat")
        thread.start()
        idle=0
        try:
            while not self.stop.is_set():
                try:
                    self.flush_receipts()
                    ready,_=self.desktop.ready()
                    if ready:
                        # 每次领取前更新 ready，桌面锁定或被占用时不领取任务。
                        job=self.request("/api/relay/claim",{"worker_id":self.id}).get("job") if self.heartbeat() else None
                        if job:self.process(job);idle=0
                        else:idle=min(idle+1,4)
                    else:idle=4
                except Exception as e:self.logger.warning("本轮暂停：%s",type(e).__name__)
                if once:break
                self.stop.wait(min(15,max(2,int(self.config.get("poll_seconds",3)))*(1+idle)))
        finally:
            self.stop.set();thread.join(timeout=20)

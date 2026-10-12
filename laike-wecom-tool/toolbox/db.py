import base64
import contextlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from .defaults import SETTINGS, TEMPLATES


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def private_write(path, content):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


class Database:
    def __init__(self, directory, initial_password=None):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "tool.db"
        key_path = self.directory / ".master-key"
        if not key_path.exists():
            if self.path.exists():
                raise RuntimeError("数据库已存在但加密密钥缺失，请从同一份备份恢复 .master-key 后启动")
            private_write(key_path, Fernet.generate_key().decode("ascii"))
        self.key = key_path.read_text(encoding="utf-8").strip().encode("ascii")
        self.fernet = Fernet(self.key)
        self.session_key = base64.urlsafe_b64decode(self.key)
        self.initialize(initial_password)

    @contextlib.contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def initialize(self, initial_password):
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.executescript("""
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS secrets (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, auth_version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS enterprises (
 id INTEGER PRIMARY KEY, account_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1, is_test INTEGER NOT NULL DEFAULT 0, sync_cursor REAL, last_sync REAL,
 last_error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS stores (
 id INTEGER PRIMARY KEY, enterprise_id INTEGER NOT NULL REFERENCES enterprises(id),
 poi_id TEXT NOT NULL, name TEXT NOT NULL, group_id TEXT NOT NULL DEFAULT '',
 group_name TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
 created_at REAL NOT NULL, UNIQUE(enterprise_id,poi_id));
CREATE TABLE IF NOT EXISTS templates (
 kind TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL, body TEXT NOT NULL,
 missing TEXT NOT NULL DEFAULT 'omit', updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots (
 enterprise_id INTEGER NOT NULL REFERENCES enterprises(id), record_type TEXT NOT NULL,
 record_id TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL,
 PRIMARY KEY(enterprise_id,record_type,record_id));
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, event_key TEXT NOT NULL UNIQUE, enterprise_id INTEGER NOT NULL REFERENCES enterprises(id),
 category TEXT NOT NULL, event_name TEXT NOT NULL, record_id TEXT NOT NULL,
 event_time REAL NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS dedup_keys (event_key TEXT PRIMARY KEY, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
 enterprise_id INTEGER NOT NULL REFERENCES enterprises(id), store_id INTEGER REFERENCES stores(id),
 category TEXT NOT NULL, group_id TEXT NOT NULL DEFAULT '', group_name TEXT NOT NULL DEFAULT '',
 body TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
 lease_token TEXT, lease_until REAL, worker_id TEXT, remote_id TEXT NOT NULL DEFAULT '',
 last_error TEXT NOT NULL DEFAULT '', result_source TEXT NOT NULL DEFAULT '',
 is_test INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL, sent_at REAL,
 retry_generation INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS messages_queue ON messages(status,next_attempt,id);
CREATE INDEX IF NOT EXISTS messages_created ON messages(created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS events_record ON events(enterprise_id,record_id);
CREATE TABLE IF NOT EXISTS attempts (
 id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES messages(id), number INTEGER NOT NULL,
 lease_token TEXT NOT NULL UNIQUE, started_at REAL NOT NULL, finished_at REAL,
 outcome TEXT NOT NULL DEFAULT 'sending', detail TEXT NOT NULL DEFAULT '', receipt TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS task_runs (
 id INTEGER PRIMARY KEY, trigger TEXT NOT NULL, status TEXT NOT NULL, started_at REAL NOT NULL,
 finished_at REAL, orders INTEGER NOT NULL DEFAULT 0, queued INTEGER NOT NULL DEFAULT 0,
 errors INTEGER NOT NULL DEFAULT 0, details TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS relay_workers (
 id TEXT PRIMARY KEY, label TEXT NOT NULL, last_seen REAL NOT NULL, ready INTEGER NOT NULL,
 detail TEXT NOT NULL DEFAULT '', groups_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, created_at REAL NOT NULL, action TEXT NOT NULL, entity_id TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '');
PRAGMA user_version=1;
""")
        with self.connect(write=True) as c:
            if "is_test" not in {row[1] for row in c.execute("PRAGMA table_info(enterprises)")}:
                c.execute("ALTER TABLE enterprises ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0")
            if "clue_cursor" not in {row[1] for row in c.execute("PRAGMA table_info(enterprises)")}:
                c.execute("ALTER TABLE enterprises ADD COLUMN clue_cursor REAL")
            if "retry_generation" not in {row[1] for row in c.execute("PRAGMA table_info(messages)")}:
                c.execute("ALTER TABLE messages ADD COLUMN retry_generation INTEGER NOT NULL DEFAULT 0")
            c.execute("INSERT OR IGNORE INTO dedup_keys SELECT event_key,created_at FROM events")
            for key, value in SETTINGS.items():
                c.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, dumps(value)))
            for kind, value in TEMPLATES.items():
                c.execute("INSERT OR IGNORE INTO templates VALUES (?,?,?,?,?,?)",
                          (kind, value["name"], int(value["enabled"]), value["body"], value["missing"], time.time()))
            if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                password = initial_password or secrets.token_urlsafe(20)
                if len(password) < 12:
                    raise ValueError("管理员初始密码至少需要 12 个字符")
                c.execute("INSERT INTO users(username,password_hash) VALUES ('admin',?)",
                          (generate_password_hash(password),))
                if not initial_password:
                    path = self.directory / ".bootstrap-password"
                    if path.exists():
                        path.unlink()
                    private_write(path, password + "\n")
        for name in ("relay_token", "ingest_token"):
            if not self.secret(name):
                self.set_secret(name, secrets.token_urlsafe(32))

    def rows(self, sql, args=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.connect() as c:
            row = c.execute(sql, args).fetchone()
            return dict(row) if row else None

    def settings(self, key):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return {**SETTINGS.get(key, {}), **json.loads(row["value"])} if row else dict(SETTINGS.get(key, {}))

    def set_settings(self, key, value):
        with self.connect(write=True) as c:
            c.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, dumps(value)))

    def secret(self, key):
        row = self.one("SELECT value FROM secrets WHERE key=?", (key,))
        return self.fernet.decrypt(row["value"].encode()).decode() if row else ""

    def set_secret(self, key, value):
        encrypted = self.fernet.encrypt(value.encode()).decode()
        with self.connect(write=True) as c:
            c.execute("INSERT INTO secrets VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, encrypted))

    def audit(self, action, entity_id="", detail="", connection=None):
        args = (time.time(), action, str(entity_id), str(detail)[:2000])
        if connection is not None:
            connection.execute("INSERT INTO audit(created_at,action,entity_id,detail) VALUES (?,?,?,?)", args)
        else:
            with self.connect(write=True) as c:
                c.execute("INSERT INTO audit(created_at,action,entity_id,detail) VALUES (?,?,?,?)", args)

    def backup(self, target):
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, contextlib.closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
        return str(target)

    def cleanup(self, now=None):
        """只清理终态正文，保留异常任务及不含客户资料的永久去重键。"""
        cutoff = (now or time.time()) - self.settings("scheduler")["history_days"] * 86400
        with self.connect(write=True) as c:
            condition = "message_id IN (SELECT id FROM messages WHERE status IN ('sent','canceled','muted','skipped_old') AND updated_at<?)"
            c.execute("DELETE FROM attempts WHERE " + condition, (cutoff,))
            deleted = c.execute("DELETE FROM messages WHERE status IN ('sent','canceled','muted','skipped_old') AND updated_at<?", (cutoff,)).rowcount
            c.execute("DELETE FROM events WHERE id NOT IN (SELECT event_id FROM messages)")
            c.execute("DELETE FROM snapshots WHERE updated_at<?", (cutoff,))
            c.execute("DELETE FROM task_runs WHERE status<>'running' AND started_at<?", (cutoff,))
            c.execute("DELETE FROM audit WHERE created_at<?", (cutoff,))
        # 增量清理复用 SQLite 空页，不在繁忙时执行 VACUUM。
        with self.connect() as c:
            c.execute("PRAGMA wal_checkpoint(PASSIVE)")
        return deleted

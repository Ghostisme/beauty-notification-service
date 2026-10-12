"""不依赖数据库服务的本机维护命令。"""
import argparse
import os
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from toolbox.db import Database


def backup(db, output, retain=7):
    output = Path(output).resolve();output.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = output / ("laike-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6] + ".zip")
    with tempfile.TemporaryDirectory(prefix=".laike-backup-", dir=output) as tmp:
        snapshot = Path(tmp) / "tool.db"
        db.backup(snapshot)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle, zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            archive.write(snapshot, "tool.db")
            archive.write(db.directory / ".master-key", ".master-key")
    for old in sorted(output.glob("laike-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[retain:]:
        old.unlink()
    return target


def main():
    parser = argparse.ArgumentParser(description="来客工具本机维护")
    parser.add_argument("command", choices=("backup", "cleanup", "check"))
    parser.add_argument("--data-dir", default=os.environ.get("TOOL_DATA_DIR", "data"))
    parser.add_argument("--output", default=None)
    parser.add_argument("--retain", type=int, default=7)
    args = parser.parse_args()
    directory = Path(args.data_dir).resolve()
    if not (directory / "tool.db").is_file() or not (directory / ".master-key").is_file():
        parser.error("未找到完整的数据目录，请先运行工具完成初始化")
    if not 1 <= args.retain <= 3650:parser.error("备份保留数量需在 1 到 3650 之间")
    db = Database(directory)
    if args.command == "backup":
        print("备份完成：", backup(db, args.output or directory / "backups", args.retain))
    elif args.command == "cleanup":
        print("已清理到期终态通知：", db.cleanup())
    else:
        with db.connect() as c:
            result = c.execute("PRAGMA integrity_check").fetchall()
            foreign = c.execute("PRAGMA foreign_key_check").fetchall()
        ok = [row[0] for row in result] == ["ok"] and not foreign
        print("数据库检查：", "正常" if ok else "需要检查")
        if not ok:raise SystemExit(1)


if __name__ == "__main__":main()

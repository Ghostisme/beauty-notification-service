import argparse
import getpass
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def configure(path, test_only=False):
    server=input("服务器地址（如 https://notify.example.com）：").strip().rstrip("/")
    parts=urlsplit(server)
    if parts.scheme not in ("http","https") or not parts.hostname:
        raise ValueError("请填写有效服务器地址")
    if parts.scheme!="https" and parts.hostname not in ("localhost","127.0.0.1","::1"):
        raise ValueError("远程发送端连接请使用 HTTPS 地址")
    token=getpass.getpass("发送端接入令牌（后台接入设置中查看）：").strip()
    if len(token)<20:raise ValueError("接入令牌不完整")
    config={"server":server,"token":token,"worker_id":"windows-wecom-1","label":"Windows 企微发送端",
            "data_dir":"sender-data","profile":"sender-data/desktop-profile.json","poll_seconds":3}
    if test_only:
        from toolbox.testing import TEST_GROUP_ID
        config["group_ids"] = [TEST_GROUP_ID]
        config["label"] = "壹心测试群发送端"
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:json.dump(config,f,ensure_ascii=False,indent=2)
    print("发送端连接配置已保存，下一步运行 --calibrate 校准企微界面。")


def main():
    parser=argparse.ArgumentParser(description="来客工具 · Windows 企微外部群发送端")
    parser.add_argument("--config",default="sender-config.json")
    parser.add_argument("--configure",action="store_true")
    parser.add_argument("--calibrate",action="store_true")
    parser.add_argument("--check",action="store_true")
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--test-only",action="store_true",help="仅领取壹心-湖南-测试消息店的任务")
    args=parser.parse_args()
    if args.configure:configure(args.config, test_only=args.test_only);return
    path=Path(args.config)
    if not path.exists():parser.error("请先运行 sender.py --configure")
    config=json.loads(path.read_text(encoding="utf-8"))
    if args.test_only:
        from toolbox.testing import TEST_GROUP_ID
        config["group_ids"] = [TEST_GROUP_ID]
        config["label"] = "壹心测试群发送端"
    if args.calibrate:
        from sender.calibrate import calibrate
        calibrate(config.get("profile","sender-data/desktop-profile.json"));return
    from sender.worker import Worker
    worker=Worker(config)
    if args.check:
        ready,detail=worker.desktop.ready();print(json.dumps({"ready":ready,"detail":detail},ensure_ascii=False));return
    from run import process_lock
    try:lock=process_lock(worker.data.resolve())
    except OSError:parser.error("此发送端数据目录已有实例运行，请先关闭重复进程")
    try:worker.run(once=args.once)
    finally:lock.close()


if __name__=="__main__":main()

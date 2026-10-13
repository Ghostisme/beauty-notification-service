import argparse
import getpass
import json
import os
import sys
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
    from sender.identity import sender_identity
    worker_id, label = sender_identity()
    config={"server":server,"token":token,"worker_id":worker_id,"label":label,
            "data_dir":"sender-data","profile":"sender-data/desktop-profile.json","poll_seconds":3}
    from toolbox.testing import TEST_GROUP_NAME
    config["group_names"] = [TEST_GROUP_NAME]
    if test_only:
        config["label"] = label + " · 壹心测试群"
    save_config(path, config)
    print("发送端连接配置已保存，初次仅负责壹心测试群。下一步运行 --calibrate 校准企微界面。")


def save_config(path, config):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:json.dump(config,f,ensure_ascii=False,indent=2)


def configure_groups(path, config):
    from sender.network import request_json
    groups = request_json(config, "/api/relay/groups")["items"]
    if not groups:
        raise ValueError("后台没有启用的群绑定，请先在企业与门店中添加")
    print("选择这台电脑负责的群。只列出后台已绑定的群；发送账号还须在企微中加入这些群。")
    for index, group in enumerate(groups, 1):
        print(str(index) + ". " + group["group_name"])
    raw = input("输入负责群的序号，用英文逗号分隔（例如 1,3；直接回车取消）：").strip()
    if not raw:
        print("已取消，原负责范围保留。");return
    parts = raw.split(",")
    if any(not part.strip().isdigit() or not 1 <= int(part.strip()) <= len(groups) for part in parts):
        raise ValueError("群序号无效，原配置未改动")
    config["group_names"] = list(dict.fromkeys(groups[int(part.strip())-1]["group_name"] for part in parts))
    config.pop("group_ids", None)
    from sender.identity import sender_identity
    config["label"] = sender_identity()[1]
    save_config(path, config)
    print("已保存负责群：" + "、".join(config["group_names"]) + "。请使用普通启动入口；测试入口仍只负责测试群。")


def main():
    parser=argparse.ArgumentParser(description="来客工具 · Windows / Mac 企微外部客户群发送端")
    parser.add_argument("--config",default="sender-config.json")
    parser.add_argument("--configure",action="store_true")
    parser.add_argument("--calibrate",action="store_true")
    parser.add_argument("--check",action="store_true")
    parser.add_argument("--groups",action="store_true",help="选择这台电脑负责的门店群，不发消息")
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--test-only",action="store_true",help="仅领取壹心-湖南-测试消息店的任务")
    parser.add_argument("--permissions",action="store_true",help="检查并申请 Mac 辅助功能和屏幕录制权限，不发消息")
    args=parser.parse_args()
    if args.permissions:
        if sys.platform != "darwin":
            print("Windows 无需此项 Mac 权限设置。");return
        from sender.macos import NativeMac
        ready, detail = NativeMac().permissions(prompt=True)
        print(detail)
        if not ready:raise SystemExit(2)
        return
    if args.configure:configure(args.config, test_only=args.test_only);return
    path=Path(args.config)
    if not path.exists():parser.error("请先运行 sender.py --configure")
    config=json.loads(path.read_text(encoding="utf-8"))
    if args.groups:
        configure_groups(path, config);return
    if args.test_only:
        from toolbox.testing import TEST_GROUP_NAME
        config.pop("group_ids", None)
        config["group_names"] = [TEST_GROUP_NAME]
        config["label"] = "壹心测试群发送端"
    if args.calibrate:
        from sender.calibrate import calibrate
        calibrate(config.get("profile","sender-data/desktop-profile.json"));return
    from sender.worker import Worker
    worker=Worker(config)
    if args.check:
        from toolbox.domain import error_text
        try:
            ready=worker.heartbeat()
            detail=worker.readiness_detail
            print(json.dumps({"server_connected":True,"ready":ready,"detail":detail},ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"server_connected":False,"ready":False,
                              "detail":error_text(exc,(worker.token,))},ensure_ascii=False))
        finally:worker.close_network()
        return
    from run import process_lock
    try:lock=process_lock(worker.data.resolve())
    except OSError:parser.error("此发送端数据目录已有实例运行，请先关闭重复进程")
    try:worker.run(once=args.once)
    finally:lock.close()


if __name__=="__main__":main()

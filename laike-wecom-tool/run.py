import argparse
import atexit
import os
import signal
from pathlib import Path


def process_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    handle = open(directory / ".process-lock", "a+b")
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def main():
    parser = argparse.ArgumentParser(description="来客门店通知工具")
    parser.add_argument("--host", default=os.environ.get("TOOL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TOOL_PORT", "8790")))
    parser.add_argument("--data-dir", default=os.environ.get("TOOL_DATA_DIR", "data"))
    parser.add_argument("--demo", action="store_true", help="使用独立演示数据；不会连接真实抖音或发送端")
    parser.add_argument("--init-only", action="store_true")
    args = parser.parse_args()
    data_path = Path(args.data_dir).resolve()
    if args.demo and args.data_dir == "data":
        data_path = Path("demo-data").resolve()
    try:
        lock = process_lock(data_path)
    except OSError:
        parser.error("此数据目录已有工具实例运行，请勿启动重复任务")
    from toolbox.web import create_app
    app = create_app(data_path, start_engine=False, demo=args.demo)
    if args.demo:
        from toolbox.demo import seed
        seed(app)
    elif (data_path / ".demo-mode").exists():
        parser.error("演示数据目录不能作为正式实例运行，请使用新的 data 目录")
    if args.init_only:
        print(f"初始化完成：{data_path}")
        return
    from waitress import create_server
    engine = app.extensions["engine"]
    if not args.demo:
        engine.start()
    atexit.register(engine.stop)
    print(f"来客门店通知工具： http://{args.host}:{args.port}", flush=True)
    bootstrap = data_path / ".bootstrap-password"
    if bootstrap.exists():
        print(f"初始账号：admin；密码请在本机读取 {bootstrap}，首次登录后可修改。", flush=True)
    # 固定单进程与四个请求线程；调度器不依赖第二个 Web worker。
    server = create_server(app, host=args.host, port=args.port, threads=4, connection_limit=64,
                           channel_timeout=45, max_request_body_size=2 * 1024 * 1024,
                           ident="LaikeTool", clear_untrusted_proxy_headers=True)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        server.close()
        lock.close()


if __name__ == "__main__":
    main()

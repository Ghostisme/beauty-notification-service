#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地打包（在你自己电脑的终端里跑）—— 生成发布包，供 scp 上传到服务器。

为什么不直接在服务器上 git pull：
    国内服务器直连 GitHub 经常只有几十 KB/s，甚至超时。
    本地网络好，改完代码本地打成几百 KB 的 tar.gz 传上去，几秒钟的事，
    服务器全程不需要访问 GitHub。

用法（在项目根目录，也就是有 .git 的那一层）：
    python tools/release.py                # 打包当前 HEAD
    python tools/release.py v1.2.0         # 打包指定 tag / commit

产物：dist/dylk-<日期>-<时间>-<commit>.tar.gz
    只含 git 跟踪的文件 —— config.json / .admin_token / data / logs / state
    都不在包里，所以解压到服务器不会覆盖密钥和数据库。
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo] + list(args),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = r.stdout.decode("utf-8", "replace").strip()
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败:\n{out}")
    return out


def is_repo(path):
    if not path or not os.path.isdir(path):
        return False
    r = subprocess.run(["git", "-C", path, "rev-parse", "--git-dir"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def find_repo():
    """依次尝试：当前目录 → 本脚本的上级目录 → 同级 beauty-notification-service。"""
    cands = [
        os.getcwd(),
        os.path.dirname(HERE),
        os.path.join(os.path.dirname(os.path.dirname(HERE)), "beauty-notification-service"),
    ]
    for c in cands:
        if is_repo(c):
            return os.path.abspath(c)
    return None


def main():
    ap = argparse.ArgumentParser(description="打包发布包（不访问 GitHub）")
    ap.add_argument("ref", nargs="?", default="HEAD", help="要打包的 tag / commit（默认 HEAD）")
    ap.add_argument("--repo", default=None, help="git 仓库目录（默认自动查找）")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo) if args.repo else find_repo()
    if not repo:
        sys.exit("✘ 没找到 git 仓库。请在 beauty-notification-service 目录里跑，或用 --repo 指定。")
    print(f"仓库目录: {repo}")

    ref = args.ref
    if git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False) == "":
        sys.exit(f"✘ 找不到版本: {ref}")

    # 提醒未提交的改动：git archive 只打包已提交内容
    dirty = git(repo, "status", "--porcelain")
    if dirty:
        print("⚠ 工作区有未提交的改动，这些改动【不会】进发布包：")
        for line in dirty.splitlines():
            print("    " + line)
        print('  想带上就先提交：git add -A && git commit -m "..."')
        print()

    out_dir = os.path.join(repo, "dist")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    short = git(repo, "rev-parse", "--short", ref)
    pkg_name = f"dylk-{stamp}-{short}.tar.gz"
    pkg = os.path.join(out_dir, pkg_name)

    git(repo, "archive", "--format=tar.gz", "--prefix=dylk/", "-o", pkg, ref)
    size_kb = os.path.getsize(pkg) / 1024.0

    print(f"✔ 发布包已生成：{pkg}")
    print(f"  大小 {size_kb:.0f} KB ｜ 基于 {ref} = {short}")
    print()
    print("─" * 64)
    print("下一步 1：上传到服务器（会提示输入服务器密码）")
    print()
    print(f'  scp "{pkg}" root@47.103.32.12:/tmp/')
    print()
    print("下一步 2：ssh 登录服务器后执行")
    print()
    print("  cd /opt/beauty-notification-service")
    print(f"  bash tools/remote-deploy.sh /tmp/{pkg_name}")
    print("─" * 64)


if __name__ == "__main__":
    main()

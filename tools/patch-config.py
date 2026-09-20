#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把旧版 config.json 补成新版能用的样子。

原则：**只补缺失的键，绝不覆盖你已经填好的任何值。**
所以来客 client_secret、企微 secret、ADMIN_TOKEN 这些真实密钥永远安全。

用法（在服务器项目目录里）：
    python3 tools/patch-config.py                      # 只补缺失项
    python3 tools/patch-config.py --fix-target         # 额外把非 outbox 的 target 改成 outbox
    python3 tools/patch-config.py --drop-placeholder   # 额外删掉 account_id 还是占位文案的空商户

跑之前建议先备份：cp config.json config.json.bak
"""

import argparse
import io
import json
import os
import shutil
import sys

CFG_PATH = os.environ.get("CONFIG_PATH", "config.json")

# 新版新增的 wecom 键 -> (默认值, 说明)
NEW_WECOM_KEYS = [
    ("target", "outbox",
     "推送通道。outbox = 服务器只写「待发队列」, 由中继用微信号发到门店微信群(全自动)"),
    ("test_group", "抖音本地生活订单通知",
     "链路测试群。后台「待发队列」页签点「发一条测试消息」时只发到这里, 不会碰门店群"),
    ("privacy_multi_customer_keywords", [],
     "多客户群提醒关键词。本项目群内只有自己人, 关闭提醒 = []"),
    ("privacy_warn_fields", [],
     "命中多客户群时提醒哪些字段。本项目关闭提醒 = []"),
]

PLACEHOLDER = "在此填入"


def load(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(path, cfg):
    """原子写回：先写临时文件再替换，避免写一半断电把配置写坏。"""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = None, None
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".config-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    shutil.move(tmp, path)


def main():
    ap = argparse.ArgumentParser(description="补全 config.json 的新增配置项")
    ap.add_argument("--fix-target", action="store_true",
                    help="把不是 outbox 的推送通道改成 outbox（备用通道一律停用）")
    ap.add_argument("--drop-placeholder", action="store_true",
                    help="删掉 account_id 仍是「在此填入account_id」的空商户")
    ap.add_argument("--path", default=CFG_PATH, help="配置文件路径（默认 config.json）")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        sys.exit("✘ 找不到配置文件: " + args.path)

    cfg = load(args.path)
    before = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
    changed, notes = [], []

    # ---- 1. wecom 下的新增键：缺什么补什么 ----
    wecom = cfg.setdefault("wecom", {})
    for key, default, why in NEW_WECOM_KEYS:
        if key not in wecom:
            wecom[key] = list(default) if isinstance(default, list) else default
            changed.append(f"wecom.{key} = {default!r}  ← {why}")

    # ---- 2. target 不是 outbox：默认只提醒（避免误改线上行为）----
    tgt = str(wecom.get("target") or "").strip().lower()
    if tgt != "outbox":
        if args.fix_target:
            wecom["target"] = "outbox"
            changed.append(f"wecom.target: {tgt or '(空)'} -> outbox  ← 收敛到微信群通道")
        else:
            notes.append(
                f"⚠ wecom.target 现在是 {tgt or '(空)'!r}，不是 outbox。\n"
                f"  本项目只用 outbox（写待发队列 → 中继用微信号发到微信群）。\n"
                f"  确认要切过来就重跑一次并加 --fix-target。")

    # ---- 3. push.fields 是否包含 phone ----
    fields = (cfg.get("push") or {}).get("fields") or []
    if "phone" not in fields:
        notes.append("ℹ push.fields 里没有 phone —— 通知里不会显示客户手机号。"
                     "需要就把它加回列表（逗号分隔的 JSON 数组）。")

    # ---- 4. 商户检查 ----
    merchants = cfg.get("merchants") or []
    placeholders, non_outbox, no_group = [], [], []
    for i, m in enumerate(merchants):
        acc = str(m.get("account_id") or "")
        name = m.get("name") or f"#{i}"
        if PLACEHOLDER in acc or not acc.strip():
            placeholders.append((i, name))
        mw = m.get("wecom") or {}
        if mw:
            mt = str(mw.get("target") or "").strip().lower()
            if mt and mt != "outbox":
                if args.fix_target:
                    mw["target"] = "outbox"
                    changed.append(f"merchants[{i}].wecom.target -> outbox")
                else:
                    non_outbox.append(name)
            if not (mw.get("wechat_group") or "").strip() and not (wecom.get("wechat_group") or "").strip():
                no_group.append(name)

    for name in no_group:
        notes.append(f"⚠ 商户「{name}」还没填「微信接收群名称」——通知会发不出去，"
                     f"在后台商户卡片里填上它的门店群名。")

    if placeholders:
        if args.drop_placeholder:
            keep = [m for i, m in enumerate(merchants)
                    if not (PLACEHOLDER in str(m.get("account_id") or "") or
                            not str(m.get("account_id") or "").strip())]
            cfg["merchants"] = keep
            changed.append(f"merchants: 删除 {len(placeholders)} 个占位空商户 "
                           f"（{', '.join(n for _, n in placeholders)}）")
        else:
            notes.append(f"ℹ 有 {len(placeholders)} 个商户的 account_id 还是占位文案"
                         f"（{', '.join(n for _, n in placeholders)}）——它们会出现在各处下拉里。"
                         f"要清掉就重跑一次并加 --drop-placeholder。")

    # ---- 5. 落盘 ----
    after = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
    if after != before:
        dump(args.path, cfg)
        print(f"✔ 已更新 {args.path}")
    else:
        print(f"✔ {args.path} 已经是最新的，无需改动")

    if changed:
        print("\n改了这些：")
        for c in changed:
            print("  • " + c)
    if notes:
        print("\n需要你留意的：")
        for n in notes:
            print("  " + n)

    # 顺手校验一下能不能被解析
    load(args.path)
    print("\nJSON 校验通过。")


if __name__ == "__main__":
    main()

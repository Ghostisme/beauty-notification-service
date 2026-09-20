# -*- coding: utf-8 -*-
"""管理后台接口冒烟测试: 健康检查 / 鉴权 / 待发队列取件 / 回报 / 重发 / 删除 / 概览。

运行: python tests/test_admin_api.py   (会拉起一个本地 8791 端口的临时服务)
"""
import os
import subprocess
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PORT = "8791"
TOKEN = "selftest-token"
env = dict(os.environ, ADMIN_HOST="127.0.0.1", ADMIN_PORT=PORT, ADMIN_TOKEN=TOKEN)
proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "web_admin.py")], env=env, cwd=ROOT,
                        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
base = f"http://127.0.0.1:{PORT}"
H = {"X-Admin-Token": TOKEN}
try:
    for _ in range(40):
        try:
            requests.get(base + "/api/health", timeout=2)
            break
        except requests.RequestException:
            time.sleep(0.25)
    else:
        raise SystemExit("服务未启动")

    h = requests.get(base + "/api/health", timeout=5).json()
    assert h["ok"] and "outbox" in h, h
    print("health ok, outbox =", h["outbox"])

    # 未授权应被拒绝
    r = requests.get(base + "/api/outbox", timeout=5)
    assert r.status_code == 401, r.status_code
    print("未带令牌 → 401 ✔")

    # 入队一批测试消息(直接走 storage, 模拟服务器已入队)
    import storage
    storage.enqueue_outbox(["【冒烟测试】新订单提醒 13812348000"],
                           merchant="冒烟商户", account_id="smoke-001",
                           channel="wechat_group", target="冒烟群")

    j = requests.get(base + "/api/outbox", params={"status": "pending"}, headers=H, timeout=5).json()
    assert j["ok"], j
    assert j["data"]["total"] >= 1, j
    item = j["data"]["items"][0]
    print(f"取件 ok: #{item['id']} → 群「{item['target']}」 状态={item['status']}")

    j = requests.post(base + "/api/outbox/ack", json={"ids": [item["id"]], "ok": True}, headers=H, timeout=5).json()
    assert j["ok"] and j["data"]["acked"] == 1, j
    print("回报 ok:", j["data"])

    j = requests.post(base + "/api/outbox/retry", json={"ids": [item["id"]]}, headers=H, timeout=5).json()
    assert j["ok"] and j["data"]["retried"] == 1, j
    print("重发置 pending ok:", j["data"]["outbox"])

    j = requests.post(base + "/api/outbox/delete", json={"ids": [item["id"]]}, headers=H, timeout=5).json()
    assert j["ok"] and j["data"]["deleted"] == 1, j
    print("删除 ok:", j["data"]["outbox"])

    # 群绑定体检(只读): 列出每个商户「配置的群名 vs 队列里还没发出去的群名」
    j = requests.get(base + "/api/group/binding", headers=H, timeout=5).json()
    assert j["ok"] and isinstance(j["data"]["bindings"], list), j
    for b in j["data"]["bindings"]:
        assert {"merchant", "configured_group", "queued_targets", "stale_targets", "stale_total"} <= set(b), b
    print("群绑定体检 ok:", [(b["merchant"], b["configured_group"], b["stale_total"])
                             for b in j["data"]["bindings"]])

    # 重绑定的异常路径: 商户不存在要被挡下, 而不是静默乱改
    j = requests.post(base + "/api/outbox/rebind", json={"merchant": "不存在的商户"},
                      headers=H, timeout=5).json()
    assert j["ok"] is False and "找不到" in j["error"], j
    print("重绑定异常路径 ok:", j["error"][:60])

    # 链路测试消息: 只能进测试群, 且用它的 id 精确清理(不能按商户名批量删)
    cfg = requests.get(base + "/api/config", headers=H, timeout=5).json()["data"]["config"]
    tg = ((cfg.get("wecom") or {}).get("test_group") or "").strip()
    assert tg, cfg.get("wecom")
    j = requests.post(base + "/api/outbox/test", json={"group": tg}, headers=H, timeout=10).json()
    assert j["ok"], j
    d = j["data"]
    assert d["target"] == tg and d["enqueued"] == 1, d
    assert "链路测试" in d["content"] and tg in d["content"] and d["id"], d
    assert "saved_test_group" not in d, "群名与配置一致时不该回写配置"
    j = requests.post(base + "/api/outbox/delete", json={"ids": [d["id"]]}, headers=H, timeout=5).json()
    assert j["ok"], j
    print("链路测试消息 ok ✔ →", tg, "(已按 id 清理)")

    j = requests.get(base + "/api/stats", headers=H, timeout=5).json()
    assert j["ok"] and "outbox" in j["data"], j
    print("stats 含 outbox ✔", j["data"]["outbox"])
    print("--- HTTP 冒烟全部通过 ---")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

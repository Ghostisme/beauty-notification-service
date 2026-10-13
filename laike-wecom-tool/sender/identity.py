"""默认使用不同电脑的稳定标识；已有配置中的 worker_id 保持有效。"""
import hashlib
import platform
import sys
import uuid


def sender_identity(system=None, machine=None):
    system = sys.platform if system is None else system
    name = {"win32": "Windows", "darwin": "Mac"}.get(system, "桌面")
    prefix = {"win32": "windows", "darwin": "macos"}.get(system, "desktop")
    machine = machine if machine is not None else platform.node() + ":" + str(uuid.getnode())
    suffix = hashlib.sha256(machine.encode("utf-8")).hexdigest()[:10]
    return prefix + "-wecom-" + suffix, name + " 企微发送端"

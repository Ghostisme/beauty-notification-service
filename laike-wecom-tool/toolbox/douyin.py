import base64
import copy
import threading
import time
from collections import OrderedDict

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import requests

from .domain import error_text, full_phone, public_phone, time_text


class PlatformError(RuntimeError):
    def __init__(self, code, description, logid=""):
        self.code = str(code)
        super().__init__(f"抖音接口 {self.code}：{description}" + (f"（日志号 {logid}）" if logid else ""))


class DouyinClient:
    """按官方商户账号分页查询；每家企业的成功游标由调用方独立提交。"""

    def __init__(self, db, session=None):
        self.db = db
        self.session = session or requests.Session()
        if session is None:
            # 平台使用出口 IP 白名单；不继承桌面代理而切换到另一公网出口。
            self.session.trust_env = False
        self._token = ""
        self._expires = 0
        self._identity = None
        self._lock = threading.RLock()
        self._decrypt_cache = OrderedDict()

    @staticmethod
    def unpack(body):
        if not isinstance(body, dict):
            raise RuntimeError("抖音接口返回格式不正确")
        data = body.get("data")
        extra = body.get("extra") if isinstance(body.get("extra"), dict) else {}
        for level in (body, data, extra):
            if not isinstance(level, dict):
                continue
            code = level.get("error_code", level.get("err_no", level.get("code", 0)))
            if code not in (None, 0, "0"):
                raise PlatformError(code, level.get("description") or level.get("message") or "接口拒绝请求", extra.get("logid", ""))
        if not isinstance(data, dict):
            raise RuntimeError("抖音接口缺少 data 对象")
        return data

    def token(self, force=False):
        with self._lock:
            cfg = self.db.settings("douyin")
            secret = self.db.secret("douyin_secret")
            identity = (cfg["client_key"], secret, cfg["base_url"])
            if not force and self._token and self._identity == identity and time.monotonic() < self._expires:
                return self._token
            if not cfg["client_key"] or not secret:
                raise ValueError("请先在接入设置填写抖音服务商应用凭证")
            r = self.session.post(cfg["base_url"].rstrip("/") + "/oauth/client_token/",
                                  json={"client_key": cfg["client_key"], "client_secret": secret,
                                        "grant_type": "client_credential"}, timeout=(5, 20))
            r.raise_for_status()
            data = self.unpack(r.json())
            token = data.get("access_token")
            if not isinstance(token, str) or not token:
                raise RuntimeError("抖音未返回 access_token，请核对服务商应用凭证")
            self._token, self._identity = token, identity
            self._expires = time.monotonic() + max(1, int(data.get("expires_in", 7200)) - 300)
            return token

    def request(self, method, path, account_id, params=None, body=None):
        cfg = self.db.settings("douyin")
        for attempt in range(3):
            token = self.token()
            try:
                r = self.session.request(method, cfg["base_url"].rstrip("/") + path,
                                         headers={"access-token": token, "content-type": "application/json",
                                                  "Rpc-Transit-Life-Account": str(account_id)},
                                         params=params, json=body, timeout=(5, 20))
                r.raise_for_status()
                return self.unpack(r.json())
            except PlatformError as e:
                if e.code in ("2190002", "2190008") and attempt == 0:
                    self.token(force=True)
                    continue
                if e.code in ("2119002", "2119003", "2100004") and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise
            except requests.RequestException as e:
                if attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise RuntimeError(error_text(e, (token, self.db.secret("douyin_secret")))) from e
        raise RuntimeError("抖音接口重试失败")

    def orders(self, account_id, start, end, max_pages=50):
        cfg = self.db.settings("douyin")
        page_size, page, cursor, fetched = 100, 1, "0", 0
        seen, seen_pages = set(), set()
        for _ in range(max_pages):
            params = {"account_id": str(account_id), "page_num": page, "page_size": page_size,
                      "update_order_start_time": int(start), "update_order_end_time": int(end)}
            if cursor:
                params["cursor"] = ",".join(str(v) for v in cursor) if isinstance(cursor, list) else str(cursor)
                params["page_num"] = 1
            data = self.request("GET", cfg["order_path"], account_id, params=params)
            items = self.order_items(data)
            signature = tuple(str(v.get("order_id")) for v in items if isinstance(v, dict))
            if signature and signature in seen_pages:
                raise RuntimeError("抖音返回重复订单页，已停止本轮同步并保留游标")
            seen_pages.add(signature)
            yield from items
            fetched += len(items)
            page_info = data.get("page") if isinstance(data.get("page"), dict) else {}
            total = data.get("total", data.get("total_count", page_info.get("total")))
            has_more = data.get("has_more")
            more = has_more in (True, 1, "1", "true") if has_more is not None else (
                fetched < int(total) if total is not None else len(items) == page_size)
            if not items or not more:
                return
            search_after = data.get("search_after") if isinstance(data.get("search_after"), dict) else {}
            next_cursor = search_after.get("CursorValue") or data.get("cursor") or data.get("next_cursor")
            if not next_cursor:
                if total is None and has_more is None:
                    return  # 官方协议：未返回 search_after 即查询结束。
                raise RuntimeError("订单仍有下一页但游标缺失，已保留同步游标")
            marker = str(next_cursor)
            if marker in seen or marker == str(cursor):
                raise RuntimeError("订单游标重复，已保留同步游标")
            seen.add(marker)
            cursor = next_cursor
            page += 1
        raise RuntimeError("本轮达到订单分页上限，已保留游标；请缩短同步时间窗或增加分页上限")

    @staticmethod
    def order_items(data):
        items = next((data[k] for k in ("order_list", "orders", "list") if isinstance(data.get(k), list)), None)
        if items is None:
            # 真实接口在时间窗内无订单时省略 orders/page/search_after，仅返回成功元信息。
            # 只接受已观察到的明确空响应；未知字段、无成功码或无效数组仍按协议错误处理。
            if (data.get("error_code") in (0, "0") and data.get("description") in (None, "")
                    and set(data) <= {"error_code", "description"}):
                return []
            raise RuntimeError("订单响应缺少 order_list/orders 数组，已保留本企业同步游标")
        if any(not isinstance(item, dict) for item in items):
            raise RuntimeError("订单响应包含无效记录，已保留本企业同步游标")
        return items

    def clues(self, account_id, start, end, max_pages=50):
        """客资中心真实线索；与订单游标分开推进，不能用订单代替留资。"""
        if not start < end or end - start > 365 * 86400:
            raise ValueError("线索查询时间窗必须递增且不超过 365 天")
        path = self.db.settings("douyin")["clue_path"]
        seen, fetched = set(), 0
        for page in range(1, min(max_pages, 100) + 1):
            data = self.request("GET", path, account_id, params={
                "account_id": str(account_id), "start_time": time_text(start), "end_time": time_text(end),
                "page": page, "page_size": 100})
            items = data.get("clue_data")
            if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
                raise RuntimeError("线索响应缺少有效 clue_data 数组，已保留线索游标")
            for item in items:
                key = str(item.get("clue_id") or "")
                if not key or key in seen:
                    raise RuntimeError("线索编号缺失或分页重复，已保留线索游标")
                seen.add(key)
                yield item
            fetched += len(items)
            info = data.get("page") if isinstance(data.get("page"), dict) else {}
            total = info.get("total")
            if not items or (total is not None and fetched >= int(total)):
                return
            if total is None and len(items) < 100:
                return
        raise RuntimeError("本轮达到线索分页上限，已保留线索游标；请缩短查询时间窗")

    def decrypt_values(self, values, account_id):
        """按已实测的 cipher_texts / results 协议解密，核对逐条成功状态。"""
        values = list(dict.fromkeys(v for v in values if isinstance(v, str) and v.startswith("Enc.")))
        cfg = self.db.settings("douyin")
        identity = (cfg["client_key"], self.db.secret("douyin_secret"), cfg["base_url"], cfg["decrypt_path"])
        mapping, errors, pending = {}, [], []
        with self._lock:
            for value in values:
                cached = self._decrypt_cache.get((identity, str(account_id), value))
                if cached and cached[0] > time.monotonic():
                    mapping[value] = cached[1]
                else:
                    pending.append(value)
        for offset in range(0, len(pending), 50):
            batch = pending[offset:offset + 50]
            try:
                data = self.request("POST", cfg["decrypt_path"], account_id,
                                    body={"account_id": str(account_id), "cipher_texts": batch})
                results = data.get("results")
                if not isinstance(results, list):
                    raise RuntimeError("解密接口未返回 results 数组")
                by_cipher = {}
                for row in results:
                    if not isinstance(row, dict) or row.get("cipher_text") not in batch:
                        continue
                    key = row["cipher_text"]
                    if key in by_cipher:
                        raise RuntimeError("解密接口返回重复密文结果")
                    by_cipher[key] = row
                for value in batch:
                    row = by_cipher.get(value, {})
                    if row.get("is_success") is True and isinstance(row.get("plain_text"), str):
                        mapping[value] = row["plain_text"]
                        with self._lock:
                            key = (identity, str(account_id), value)
                            self._decrypt_cache[key] = (time.monotonic() + 3600, row["plain_text"])
                            self._decrypt_cache.move_to_end(key)
                            while len(self._decrypt_cache) > 1024:
                                self._decrypt_cache.popitem(last=False)
                    else:
                        errors.append("有字段未能解密（错误码 " + str(row.get("error_code", "结果缺失")) + "）")
            except Exception as exc:
                errors.append(error_text(exc, (self._token, self.db.secret("douyin_secret"))))
        return mapping, "; ".join(dict.fromkeys(errors))[:1500]

    @staticmethod
    def decrypt_legacy(value, secret):
        """官方旧版 AES-CBC：补齐/左右裁剪至32字节，IV取后16字节。"""
        key = secret.encode("utf-8")
        if len(key) < 32:
            missing = 32 - len(key)
            key = b"#" * ((missing + 1) // 2) + key + b"#" * (missing // 2)
        elif len(key) > 32:
            left = (len(key) - 32 + 1) // 2
            key = key[left:left + 32]
        cipher = base64.b64decode(value, validate=True)
        decryptor = Cipher(algorithms.AES(key), modes.CBC(key[16:])).decryptor()
        padded = decryptor.update(cipher) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")

    def decrypt_clues(self, records, account_id):
        result = copy.deepcopy(records)
        if not self.db.settings("douyin")["decrypt_enabled"]:
            for row in result:
                row["phone"] = ""
            return result, "完整手机号解密未开启"
        values = [row.get("enc_telephone") for row in result]
        mapping, warning = self.decrypt_values(values, account_id)
        errors = [warning] if warning else []
        for row in result:
            enc, legacy = row.get("enc_telephone"), row.get("telephone")
            phone = mapping.get(enc, "")
            if not enc and legacy:
                try:
                    phone = public_phone(legacy) or self.decrypt_legacy(legacy, self.db.secret("douyin_secret"))
                except Exception:
                    errors.append("有旧版线索联系电话未能解密")
            row["phone"] = full_phone(phone) or public_phone(phone)
        return result, "; ".join(dict.fromkeys(errors))[:1500]

    def decrypt_orders(self, orders, account_id):
        """仅调用平台批量解密能力；没有权限时保留原值并返回可查看的错误。"""
        result = copy.deepcopy(orders)
        if not self.db.settings("douyin")["decrypt_enabled"]:
            return result, ""
        fields = []
        for order in result:
            holders = [order.get("buyer_info"), order.get("receiver_info")]
            holders.extend(order.get("contacts") or [])
            for holder in holders:
                if not isinstance(holder, dict):
                    continue
                for key in ("phone", "phone_encrypt", "name", "buyer_phone", "buyer_real_phone", "receiver_phone", "receiver_real_phone"):
                    value = holder.get(key)
                    if isinstance(value, str) and value.startswith("Enc."):
                        fields.append((holder, key, value))
        values = list(dict.fromkeys(value for _, _, value in fields))
        mapping, warning = self.decrypt_values(values, account_id)
        for holder, key, value in fields:
            if mapping.get(value):
                holder[key] = mapping[value]
        return result, warning

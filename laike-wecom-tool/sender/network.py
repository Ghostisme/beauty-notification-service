"""发送端的 HTTPS 连接；所有接口共用认证、错误类型和证书校验。"""
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import certifi
import requests


def transport_name(config):
    name = config.get("http_transport")
    if name is None:
        name = "browser" if sys.platform == "win32" and urlsplit(config["server"]).scheme == "https" else "requests"
    if name not in ("browser", "requests"):
        raise ValueError("http_transport 只支持 browser 或 requests")
    return name


class BrowserSession:
    def __init__(self):
        try:
            from curl_cffi import requests as browser_requests
            from curl_cffi.requests import exceptions
        except ImportError as exc:
            raise RuntimeError("请先更新发送端依赖：python -m pip install -r requirements-sender.lock") from exc
        self.errors = exceptions
        self.ca_directory = tempfile.TemporaryDirectory(prefix="laike-sender-ca-")
        try:
            bundle = Path(self.ca_directory.name) / "cacert.pem"
            # Windows 原生 curl 无法打开项目中文路径中的 CA 文件。
            bundle.write_bytes(Path(certifi.where()).read_bytes())
            if sys.platform == "win32" and not str(bundle).isascii():
                raise RuntimeError("请将 Windows TEMP 设置到英文路径后重新启动发送端")
            self.session = browser_requests.Session(impersonate="chrome", verify=str(bundle), trust_env=True)
        except BaseException:
            self.ca_directory.cleanup()
            raise

    def _request(self, method, url, **kwargs):
        try:
            response = self.session.request(method, url, **kwargs)
        except self.errors.SSLError as exc:
            raise requests.exceptions.SSLError(str(exc)) from exc
        except self.errors.Timeout as exc:
            raise requests.Timeout(str(exc)) from exc
        except self.errors.ConnectionError as exc:
            raise requests.ConnectionError(str(exc)) from exc
        except self.errors.RequestException as exc:
            raise requests.RequestException(str(exc)) from exc
        if not 200 <= response.status_code < 300:
            raise requests.HTTPError(f"发送端接口返回 HTTP {response.status_code}", response=response)
        return response

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)

    def close(self):
        try:
            self.session.close()
        finally:
            self.ca_directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def create_session(config):
    return BrowserSession() if transport_name(config) == "browser" else requests.Session()


def request_json(config, path, body=None, session=None):
    if session is None and transport_name(config) == "browser":
        with create_session(config) as session:
            return request_json(config, path, body, session)
    client = session if session is not None else requests
    headers = {"Authorization": "Bearer " + config["token"]}
    kwargs = {"headers": headers, "timeout": (5, 15), "allow_redirects": False}
    url = config["server"].rstrip("/") + path
    # 不在连接失败后重放 POST，避免重复领取任务或提交状态。
    response = client.get(url, **kwargs) if body is None else client.post(url, json=body, **kwargs)
    response.raise_for_status()
    return response.json()

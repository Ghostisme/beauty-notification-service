import datetime
import json
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from sender.network import BrowserSession, request_json
from sender.worker import Worker


@pytest.fixture
def tls_api(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    directory = tmp_path / "中文证书目录"
    directory.mkdir()
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append({"method": "GET", "path": self.path, "auth": self.headers.get("Authorization")})
            self.reply(200, {"items": [{"group_id": "fixture-group", "group_name": "测试群"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            calls.append({"method": "POST", "path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            if self.path == "/api/relay/claim":
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            self.reply(409 if self.path == "/api/relay/result" else 200, {"ok": True})

        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {"server": f"https://localhost:{server.server_port}", "token": "network-fixture-token",
              "http_transport": "browser"}
    try:
        yield config, cert_path, calls
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_verified_https_with_unicode_ca_source_auth_and_json(tls_api, monkeypatch):
    config, cert_path, calls = tls_api
    monkeypatch.setattr("sender.network.certifi.where", lambda: str(cert_path))
    with BrowserSession() as session:
        cached_ca = Path(session.ca_directory.name)
        assert request_json(config, "/api/relay/groups", session=session)["items"][0]["group_id"] == "fixture-group"
        assert request_json(config, "/api/relay/heartbeat", {"ready": True}, session)["ok"]
    assert not cached_ca.exists()
    assert [c["method"] for c in calls] == ["GET", "POST"]
    assert all(c["auth"] == "Bearer network-fixture-token" for c in calls)
    assert calls[1]["body"] == {"ready": True}


def test_untrusted_certificate_is_rejected_before_http_request(tls_api):
    config, _, calls = tls_api
    with pytest.raises(requests.exceptions.SSLError):
        request_json(config, "/api/relay/groups")
    assert calls == []


def test_trusted_certificate_for_wrong_host_is_rejected(tls_api, monkeypatch):
    config, cert_path, calls = tls_api
    monkeypatch.setattr("sender.network.certifi.where", lambda: str(cert_path))
    config["server"] = config["server"].replace("localhost", "127.0.0.1")
    with pytest.raises(requests.exceptions.SSLError):
        request_json(config, "/api/relay/groups")
    assert calls == []


def test_post_connection_loss_does_not_replay_committed_claim(tls_api, monkeypatch):
    config, cert_path, calls = tls_api
    monkeypatch.setattr("sender.network.certifi.where", lambda: str(cert_path))
    with pytest.raises(requests.RequestException):
        request_json(config, "/api/relay/claim", {"worker_id": "fixture-worker"})
    assert len(calls) == 1
    assert calls[0]["path"] == "/api/relay/claim"


def test_receipt_conflict_stops_replay_with_browser_http_error(tls_api, monkeypatch, tmp_path):
    config, cert_path, calls = tls_api
    monkeypatch.setattr("sender.network.certifi.where", lambda: str(cert_path))
    worker = Worker({**config, "data_dir": str(tmp_path / "ledger")}, SimpleNamespace())
    worker.ledger.update("fixture-key", "fixture-group", "sent", {"message_id": 1}, pending=True)
    try:
        worker.flush_receipts()
        assert worker.ledger.pending() == []
        assert len(calls) == 1 and calls[0]["path"] == "/api/relay/result"
    finally:
        worker.close_network()

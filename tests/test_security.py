"""SR-1 安全修復的回歸測試（SECURITY-AUDIT F1／F2／F3／F5／F6）。

全部走本機隔離實例：tmp DATA_ROOT、合成資料、canary 假 key；
沒有任何真實網路或使用者資料。
"""

from __future__ import annotations

import dataclasses
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from shop import config as config_mod, security
from tests.conftest import make_jpeg

TEST_HEADERS = {"X-Requested-With": "ItemTrace"}


def _simple_client(app_config, **kwargs):
    """建立 TestClient（可選擇是否帶標頭）。"""
    from fastapi.testclient import TestClient

    from shop.api import create_app

    return TestClient(
        create_app(app_config), base_url="http://localhost", **kwargs
    )


# ----------------------------------------------------------------------
# F1／F3：Host 驗證
# ----------------------------------------------------------------------


def test_host_allowlist_accepts_loopback_forms(client):
    assert client.get("/api/items").status_code == 200
    assert client.get("/api/items", headers={"Host": "127.0.0.1"}).status_code == 200
    assert client.get("/api/items", headers={"Host": "127.0.0.1:8731"}).status_code == 200
    assert client.get("/api/items", headers={"Host": "[::1]:8731"}).status_code == 200
    assert client.get("/api/items", headers={"Host": "localhost:8731"}).status_code == 200


def test_host_rebinding_domain_is_rejected_before_processing(client):
    response = client.get("/api/items", headers={"Host": "evil.example"})
    assert response.status_code == 403
    assert "Host" in response.json()["detail"]


def test_host_extra_allowlist_from_config(config):
    cfg = dataclasses.replace(config, allowed_hosts=("desktop.local",))
    with _simple_client(cfg, headers=TEST_HEADERS) as c:
        assert c.get("/api/items", headers={"Host": "desktop.local:8731"}).status_code == 200
        assert c.get("/api/items", headers={"Host": "other.local"}).status_code == 403


# ----------------------------------------------------------------------
# F3：Origin 驗證＋變更端點標頭
# ----------------------------------------------------------------------


def test_mutation_without_custom_header_is_rejected(config):
    with _simple_client(config) as bare:
        response = bare.post("/api/items", json={"name": "x"})
    assert response.status_code == 403
    assert "X-Requested-With" in response.json()["detail"]


def test_cross_origin_mutation_is_rejected(config):
    with _simple_client(config, headers=TEST_HEADERS) as c:
        with_origin = c.post(
            "/api/items", json={"name": "x"},
            headers={"Origin": "http://evil.example"},
        )
        assert with_origin.status_code == 403
        assert "Origin" in with_origin.json()["detail"]

        # 連帶上自訂標頭也不行：Origin 本身不被信任
        both = c.post(
            "/api/items", json={"name": "x"},
            headers={"Origin": "http://evil.example"},
        )
        assert both.status_code == 403

        null_origin = c.post(
            "/api/items", json={"name": "x"}, headers={"Origin": "null"}
        )
        assert null_origin.status_code == 403

        wrong_port = c.post(
            "/api/items", json={"name": "x"},
            headers={"Origin": "http://localhost:9999"},
        )
        assert wrong_port.status_code == 403


def test_same_origin_mutation_and_non_browser_flow_succeed(config, client):
    # 瀏覽器同源：Origin 與請求一致
    browser = client.post(
        "/api/items", json={"name": "browser-flow"},
        headers={"Origin": "http://localhost"},
    )
    assert browser.status_code == 201

    # 非瀏覽器：沒有 Origin，但有標頭（scripts/curl 的模式）
    script = client.post("/api/items", json={"name": "script-flow"})
    assert script.status_code == 201


def test_safe_methods_do_not_require_the_header(config):
    with _simple_client(config) as bare:
        assert bare.get("/api/items").status_code == 200
        assert bare.get("/api/health").status_code == 200


# ----------------------------------------------------------------------
# F2：已儲存的 key 不外送到呼叫者指定的 URL
# ----------------------------------------------------------------------


class _Receiver(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self.server.received.append(
            {"auth": self.headers.get("Authorization", "")}
        )
        payload = json.dumps({"choices": [{"message": {"content": "pong"}}]})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))

    def log_message(self, *args):  # silence
        return


@pytest.fixture()
def receiver():
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    server.received = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


@pytest.fixture()
def canary_config_file(config, monkeypatch, tmp_path):
    """把 ai_config 指向一個帶 canary key 的暫存設定檔。"""
    from shop import ai_config

    path = tmp_path / "ai_config.local.json"
    path.write_text(
        json.dumps({
            "api_key": "sk-or-v1-CANARY-SR1-000000000000",
            "provider": "openrouter",
            "model": "canary/model",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_config, "config_path", lambda *a, **k: path)
    return path


def test_stored_key_is_never_forwarded_to_arbitrary_url(
    config, client, receiver, canary_config_file
):
    """審計 F2 的核心回歸：自訂 base_url＋已存 key → 400，接收端零請求。"""
    response = client.post("/api/settings/ai/test", json={
        "provider": "custom",
        "base_url": f"http://127.0.0.1:{receiver.server_address[1]}",
        "api_key": "",
    })
    assert response.status_code == 400
    assert "臨時 API key" in response.json()["detail"]
    assert receiver.received == []          # 沒有任何外送


def test_custom_url_with_temporary_key_uses_only_that_key(
    config, client, receiver, canary_config_file
):
    """自訂端點仍可用——但用的是這次帶進來的臨時 key，不是已存的那把。"""
    temp_key = "sk-or-v1-TEMP-0000000000000000"
    response = client.post("/api/settings/ai/test", json={
        "provider": "custom",
        "base_url": f"http://127.0.0.1:{receiver.server_address[1]}",
        "api_key": temp_key,
    })
    assert response.status_code == 200
    assert len(receiver.received) == 1
    assert receiver.received[0]["auth"] == f"Bearer {temp_key}"
    assert "CANARY" not in json.dumps(receiver.received)


def test_preset_url_reuses_stored_key(
    config, client, receiver, canary_config_file, monkeypatch
):
    """已知 provider 端點仍可沿用已存 key（不破壞既有設定流程）。"""
    from shop import ai_config

    calls = []

    def fake_urlopen(request_object, timeout=None):
        calls.append(request_object.full_url)

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        return _Response()

    monkeypatch.setattr(
        "shop.settings.urllib.request.urlopen", fake_urlopen
    )
    response = client.post("/api/settings/ai/test", json={
        "provider": "openrouter", "model": "canary/model", "api_key": "",
    })
    assert response.status_code == 200
    assert calls == [
        ai_config.PROVIDER_BASE_URLS["openrouter"] + "/chat/completions"
    ]
    assert receiver.received == []


# ----------------------------------------------------------------------
# F5：綁定預設與 opt-in
# ----------------------------------------------------------------------


def test_loopback_bind_host_detection():
    assert security.is_loopback_bind_host("127.0.0.1")
    assert security.is_loopback_bind_host("127.0.0.2")
    assert security.is_loopback_bind_host("::1")
    assert security.is_loopback_bind_host("localhost")
    assert not security.is_loopback_bind_host("0.0.0.0")
    assert not security.is_loopback_bind_host("::")
    assert not security.is_loopback_bind_host("192.168.1.50")


def test_config_defaults_are_loopback_and_lan_requires_opt_in(config):
    assert config_mod.DEFAULTS["server_host"] == "127.0.0.1"
    assert config_mod.DEFAULTS["allow_lan"] is False
    assert config.allow_lan is False

    assert security.require_lan_opt_in(config, "0.0.0.0") is True
    assert security.require_lan_opt_in(config, "192.168.1.50") is True
    assert security.require_lan_opt_in(config, "127.0.0.1") is False
    lan_ok = dataclasses.replace(config, allow_lan=True)
    assert security.require_lan_opt_in(lan_ok, "0.0.0.0") is False


# ----------------------------------------------------------------------
# F6：媒體供應（nosniff／附件／CSP）
# ----------------------------------------------------------------------


def _upload_to_inbox(client, name, data, content_type):
    response = client.post(
        "/api/inbox/photos",
        files=[("files", (name, data, content_type))],
    )
    assert response.status_code == 201
    return next(
        entry["relative"] for entry in response.json()["entries"]
        if entry["relative"].endswith(name)
    )


def test_uploaded_html_is_served_as_hardened_attachment(config, client):
    relative = _upload_to_inbox(
        client, "evil.html",
        b"<html><script>alert(1)</script></html>", "text/html",
    )
    response = client.get(f"/files/{relative}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert response.headers.get("content-disposition") == "attachment"
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert "default-src 'none'" in response.headers.get("content-security-policy", "")


def test_images_are_served_inline_with_nosniff_and_csp(config, client):
    relative = _upload_to_inbox(
        client, "photo.jpg", make_jpeg(exif="2026:10:01 10:00:00"), "image/jpeg",
    )
    response = client.get(f"/files/{relative}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.headers.get("content-disposition") is None   # 仍可 inline 顯示
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert "default-src 'none'" in response.headers.get("content-security-policy", "")


def test_spa_and_api_responses_carry_security_headers(client):
    spa = client.get("/")
    assert spa.status_code == 200
    assert spa.headers.get("x-content-type-options") == "nosniff"
    assert spa.headers.get("x-frame-options") == "DENY"
    assert "default-src 'self'" in spa.headers.get("content-security-policy", "")

    api = client.get("/api/items")
    assert api.headers.get("x-content-type-options") == "nosniff"
    assert api.headers.get("referrer-policy") == "no-referrer"


# ----------------------------------------------------------------------
# F6：前端慣例的靜態守門（CSP 相容＋escaping）
# ----------------------------------------------------------------------


def test_web_js_has_no_inline_event_handlers():
    """CSP script-src 'self' 會擋 inline on*：web/ 不允許再出現。"""
    import re
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "web"
    offenders = []
    for path in web.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\son(?:error|load|click)=", text):
            offenders.append(path.relative_to(web).as_posix())
    assert offenders == [], f"發現 inline 事件處理器：{offenders}"


def test_views_import_the_escape_helper():
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "web"
    for name in ("home.js", "capture.js", "record-detail.js"):
        text = (web / "views" / name).read_text(encoding="utf-8")
        assert "escapeHtml" in text, f"{name} 沒有使用 escapeHtml"

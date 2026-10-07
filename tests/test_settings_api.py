"""`/api/settings/ai` 的契約與安全性。

最重要的一件事：**回應裡永遠不能出現 API key**。
第二重要：**只有 loopback 可以改設定**。

這裡用 fake provider，完全不對 OpenRouter 發請求。
"""

from __future__ import annotations

import io
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from shop import ai_config

SECRET = "sk-or-v1-TEST-LOCAL-KEY-0000000000"
SECRET_PREFIX = "sk-or-v1-"
NEW_SECRET = "sk-or-v1-ANOTHER-KEY-00000000000"

ROOT = Path(__file__).resolve().parents[1]
LOOPBACK = ("127.0.0.1", 50000)
LOOPBACK_V6 = ("::1", 50000)
LAN = ("192.168.0.149", 50000)


@pytest.fixture()
def config_file(tmp_path, monkeypatch):
    """把設定檔指到暫存位置，測試絕不碰真的 tools/ai_config.local.json。"""
    path = tmp_path / "ai_config.local.json"
    monkeypatch.setattr(ai_config, "config_path", lambda *a, **k: path)
    return path


@pytest.fixture()
def local(client_factory):
    """來自 127.0.0.1 的 client。"""
    with client_factory(LOOPBACK) as c:
        yield c


@pytest.fixture()
def lan(client_factory):
    """來自區網的 client。"""
    with client_factory(LAN) as c:
        yield c


@pytest.fixture()
def seeded(config_file):
    config_file.write_text(
        json.dumps({"api_key": SECRET, "model": "seed/model:free"}),
        encoding="utf-8",
    )
    return config_file


@pytest.fixture()
def fake_provider(monkeypatch):
    """取代 urllib.urlopen，記錄請求並回假回應。"""
    calls: list[dict] = []

    def install(status=200, body=None, raises=None):
        def fake_urlopen(request, timeout=None):
            calls.append({
                "url": request.full_url,
                "auth": request.get_header("Authorization"),
                "body": json.loads(request.data) if request.data else None,
            })
            if raises is not None:
                raise raises
            payload = body if body is not None else {"choices": [{"message": {"content": "pong"}}]}
            return io.BytesIO(json.dumps(payload).encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return calls

    return install


# ----------------------------------------------------------------------
# 1. 頁面
# ----------------------------------------------------------------------


def test_settings_page_loads(client):
    response = client.get("/settings")
    assert response.status_code == 200
    assert "/static/settings.js" in response.text


def test_settings_page_is_not_in_the_api_contract(client):
    assert "/settings" not in client.get("/openapi.json").json()["paths"]
    assert "/api/settings/ai" in client.get("/openapi.json").json()["paths"]


# ----------------------------------------------------------------------
# 2-3. GET 不回傳 key
# ----------------------------------------------------------------------


def test_get_never_returns_the_key(local, seeded):
    response = local.get("/api/settings/ai")
    assert response.status_code == 200
    raw = response.text
    assert SECRET not in raw, "GET 回應裡有 API key"
    assert "api_key" not in response.json()


def test_get_reports_configured_and_model(local, seeded):
    body = local.get("/api/settings/ai").json()
    assert body["configured"] is True
    assert body["model"] == "seed/model:free"
    assert body["provider"] == "openrouter"
    assert body["base_url"] == ai_config.DEFAULT_BASE_URL
    assert body["presets"] == ai_config.PROVIDER_BASE_URLS
    assert body["default_model"] == ai_config.DEFAULT_MODEL
    assert body["config_file"] == "tools/ai_config.local.json"


def test_get_when_unconfigured(local, config_file):
    body = local.get("/api/settings/ai").json()
    assert body["configured"] is False
    assert body["model"] == ai_config.DEFAULT_MODEL
    assert body["base_url"] == ai_config.DEFAULT_BASE_URL
    assert not config_file.exists(), "讀取不該憑空造出設定檔"


def test_get_is_readable_from_lan(lan, seeded):
    """讀取沒有秘密，所以區網也能看。"""
    response = lan.get("/api/settings/ai")
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["can_edit"] is True
    assert response.json()["is_loopback"] is False
    assert SECRET not in response.text


def test_settings_html_never_contains_a_key(client, seeded):
    assert SECRET not in client.get("/settings").text


# ----------------------------------------------------------------------
# 4-5. 修改 model / key
# ----------------------------------------------------------------------


def test_localhost_can_change_the_model(local, seeded):
    response = local.post("/api/settings/ai", json={"model": "new/model:free"})
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "new/model:free"
    assert body["model_changed"] is True
    assert json.loads(seeded.read_text(encoding="utf-8"))["model"] == "new/model:free"


def test_localhost_can_change_the_key(local, seeded):
    response = local.post("/api/settings/ai", json={"api_key": NEW_SECRET})
    assert response.status_code == 200
    assert response.json()["api_key_changed"] is True
    stored = json.loads(seeded.read_text(encoding="utf-8"))
    assert stored["api_key"] == NEW_SECRET
    assert SECRET not in stored["api_key"]


def test_post_response_never_contains_a_key(local, seeded):
    response = local.post("/api/settings/ai", json={"api_key": NEW_SECRET})
    assert SECRET not in response.text
    assert NEW_SECRET not in response.text
    assert "api_key" not in response.json()


# ----------------------------------------------------------------------
# 6. 空白 key 不覆蓋
# ----------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    {},
    {"model": "new/model:free"},
    {"api_key": None},
    {"api_key": ""},
    {"api_key": "   "},
])
def test_blank_api_key_keeps_the_existing_one(local, seeded, body):
    """密碼欄留白不是清除。這是最容易把 key 弄丟的地方。"""
    response = local.post("/api/settings/ai", json=body)
    assert response.status_code == 200, response.text
    assert json.loads(seeded.read_text(encoding="utf-8"))["api_key"] == SECRET
    assert response.json()["api_key_changed"] is False


def test_changing_model_alone_keeps_the_key(local, seeded):
    local.post("/api/settings/ai", json={"model": "another/model:free"})
    assert json.loads(seeded.read_text(encoding="utf-8"))["api_key"] == SECRET


# ----------------------------------------------------------------------
# 7. 明確 clear 才會清除
# ----------------------------------------------------------------------


def test_clear_key_removes_it_but_keeps_the_model(local, seeded):
    response = local.post("/api/settings/ai/clear-key")
    assert response.status_code == 200
    assert response.json()["configured"] is False
    stored = json.loads(seeded.read_text(encoding="utf-8"))
    assert "api_key" not in stored
    assert stored["model"] == "seed/model:free"


def test_clear_then_analyze_item_cannot_run(local, seeded):
    """清掉之後 adapter 會明確報錯，不會靜默用空 key。"""
    local.post("/api/settings/ai/clear-key")
    with pytest.raises(ai_config.AiConfigError) as excinfo:
        ai_config.load_config(seeded)
    assert "缺少 api_key" in str(excinfo.value)


def test_clear_response_never_contains_a_key(local, seeded):
    response = local.post("/api/settings/ai/clear-key")
    assert SECRET not in response.text


# ----------------------------------------------------------------------
# 8. malformed config 不洩漏
# ----------------------------------------------------------------------


def test_malformed_config_error_is_redacted(local, config_file):
    config_file.write_text('{"api_key": "' + SECRET + '", oops', encoding="utf-8")
    response = local.post("/api/settings/ai", json={"model": "m:free"})
    assert response.status_code == 400
    assert SECRET not in response.text
    assert "不是合法 JSON" in response.json()["detail"]


def test_config_error_message_never_echoes_the_file(local, config_file):
    """設定檔壞掉要讓使用者看得見、看得懂，但不能把內容印出來。"""
    config_file.write_text('{"api_key": "' + SECRET + '", "model": 123}', encoding="utf-8")
    response = local.get("/api/settings/ai")
    assert response.status_code == 400
    assert SECRET not in response.text
    assert "model 必須是字串" in response.json()["detail"]


# ----------------------------------------------------------------------
# 9. 測試 API
# ----------------------------------------------------------------------


def test_test_api_sends_a_minimal_request(local, seeded, fake_provider):
    calls = fake_provider()
    response = local.post("/api/settings/ai/test", json={})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert len(calls) == 1
    # 只送 model + messages，不碰 ItemTrace、不送照片
    assert calls[0]["url"].startswith("https://openrouter.ai/")
    assert calls[0]["body"]["model"] == "seed/model:free"
    assert calls[0]["body"]["messages"] == [{"role": "user", "content": "ping"}]
    assert "response_format" not in calls[0]["body"]

def test_test_api_hits_the_google_endpoint(local, config_file, fake_provider):
    """provider=google 時打 Gemini 的 OpenAI 相容端點。"""
    config_file.write_text(json.dumps(
        {"api_key": SECRET, "model": "gemini-3.8-flash", "provider": "google"}
    ), encoding="utf-8")
    calls = fake_provider()
    response = local.post("/api/settings/ai/test", json={})
    assert response.status_code == 200
    assert calls[0]["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )

def test_test_api_hits_custom_base_url(local, config_file, fake_provider):
    config_file.write_text(json.dumps(
        {"api_key": SECRET, "model": "m", "provider": "custom",
         "base_url": "https://my-proxy.internal/v1"}
    ), encoding="utf-8")
    calls = fake_provider()
    response = local.post("/api/settings/ai/test", json={})
    assert response.status_code == 200
    assert calls[0]["url"] == "https://my-proxy.internal/v1/chat/completions"

def test_test_api_can_test_an_unsaved_provider(local, seeded, fake_provider):
    """剛填的 provider / base_url 也能先測，不必先存。"""
    calls = fake_provider()
    response = local.post("/api/settings/ai/test",
                          json={"provider": "google"})
    assert response.status_code == 200
    assert calls[0]["url"].startswith(
        "https://generativelanguage.googleapis.com/v1beta/openai/")


def test_test_api_uses_the_stored_key(local, seeded, fake_provider):
    calls = fake_provider()
    local.post("/api/settings/ai/test", json={})
    assert calls[0]["auth"] == "Bearer " + SECRET


def test_test_api_can_test_an_unsaved_key(local, seeded, fake_provider):
    """剛貼上還沒存的 key 也能先測。"""
    calls = fake_provider()
    response = local.post("/api/settings/ai/test", json={"api_key": NEW_SECRET})
    assert response.status_code == 200
    assert calls[0]["auth"] == "Bearer " + NEW_SECRET
    assert json.loads(seeded.read_text(encoding="utf-8"))["api_key"] == SECRET, \
        "測試不該順手把 key 存起來"


def test_test_api_uses_the_typed_model(local, seeded, fake_provider):
    calls = fake_provider()
    local.post("/api/settings/ai/test", json={"model": "typed/model:free"})
    assert calls[0]["body"]["model"] == "typed/model:free"


def test_test_api_success_response_has_no_key(local, seeded, fake_provider):
    fake_provider()
    response = local.post("/api/settings/ai/test", json={})
    assert SECRET not in response.text
    assert "api_key" not in response.json()


def test_test_api_failure_shows_the_real_error(local, seeded, fake_provider, monkeypatch):
    error = urllib.error.HTTPError(
        "https://openrouter.ai", 401, "Unauthorized", {},
        io.BytesIO(json.dumps({"error": {"message": "No auth credentials found"}}).encode()),
    )
    fake_provider(raises=error)
    response = local.post("/api/settings/ai/test", json={})
    assert response.status_code == 400
    assert "API 測試失敗" in response.json()["detail"]
    assert "No auth credentials found" in response.json()["detail"]


def test_test_api_failure_redacts_a_key_echoed_by_the_provider(
    local, seeded, fake_provider
):
    """就算 provider 把 key 原樣退回來，訊息裡也不能有。"""
    error = urllib.error.HTTPError(
        "https://openrouter.ai", 401, "Unauthorized", {},
        io.BytesIO(json.dumps({"error": f"bad key {SECRET}"}).encode()),
    )
    fake_provider(raises=error)
    response = local.post("/api/settings/ai/test", json={})
    assert response.status_code == 400
    assert SECRET not in response.text
    detail = response.json()["detail"]
    assert "***" in detail
    assert SECRET_PREFIX not in detail


def test_test_api_without_configuration_is_a_clear_error(local, config_file, fake_provider):
    fake_provider()
    response = local.post("/api/settings/ai/test", json={})
    assert response.status_code == 400
    assert "找不到" in response.json()["detail"]


# ----------------------------------------------------------------------
# 10. 區網：受信任區網可操作（server 刻意只服務區網）
# ----------------------------------------------------------------------


@pytest.mark.parametrize("address", [LOOPBACK, LOOPBACK_V6])
def test_loopback_can_edit(client_factory, seeded, address):
    with client_factory(address) as c:
        assert c.get("/api/settings/ai").json()["can_edit"] is True
        assert c.get("/api/settings/ai").json()["is_loopback"] is True
        assert c.post("/api/settings/ai", json={"model": "m:free"}).status_code == 200


def test_lan_can_change_the_model(lan, seeded):
    """區網裝置（例如手機）可以改設定 —— 與「區網可讀寫所有
    商品資料」的信任模型一致。若不信任區網，把 server_host
    改回 127.0.0.1。"""
    response = lan.post("/api/settings/ai", json={"model": "hacked/model"})
    assert response.status_code == 200
    assert json.loads(seeded.read_text(encoding="utf-8"))["model"] == "hacked/model"

def test_lan_can_change_the_key(lan, seeded):
    response = lan.post("/api/settings/ai", json={"api_key": "sk-or-v1-HACKED"})
    assert response.status_code == 200
    assert json.loads(seeded.read_text(encoding="utf-8"))["api_key"] == "sk-or-v1-HACKED"

def test_lan_can_clear_the_key(lan, seeded):
    assert lan.post("/api/settings/ai/clear-key").status_code == 200
    assert "api_key" not in json.loads(seeded.read_text(encoding="utf-8"))

def test_lan_can_test_the_api(lan, seeded, fake_provider):
    calls = fake_provider()
    assert lan.post("/api/settings/ai/test", json={}).status_code == 200
    assert len(calls) == 1

def test_spoofed_headers_do_not_change_anything(client_factory, seeded):
    """來源判斷只看 socket 對端位址，偽造標頭不影響任何事
    （現在區網本來就能寫，這個測試釘住「判斷不靠標頭」）。"""
    with client_factory(LAN) as c:
        response = c.post(
            "/api/settings/ai",
            json={"api_key": "sk-or-v1-SPOOFED"},
            headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1",
                     "Host": "localhost"},
        )
        assert response.status_code == 200
    assert json.loads(seeded.read_text(encoding="utf-8"))["api_key"] == "sk-or-v1-SPOOFED"


def test_loopback_detection_is_not_via_headers():
    """is_loopback() 只看 socket 對端位址，不讀任何使用者可控的標頭。

    模組 docstring 會提到這些標頭（說明為什麼不用），所以只檢查函式本體。
    """
    source = (ROOT / "shop" / "settings.py").read_text(encoding="utf-8")
    body = source.split("def is_loopback(", 1)[1].split("\ndef ", 1)[0]
    body = re.sub(r'""".*?"""', "", body, flags=re.S)   # 拿掉 docstring
    assert "request.headers" not in body
    assert "x-forwarded-for" not in body.lower()
    assert "x-real-ip" not in body.lower()


# ----------------------------------------------------------------------
# 12. 路徑固定，不能由瀏覽器指定
# ----------------------------------------------------------------------


def test_api_accepts_no_path_parameter():
    """API 不接受 path / filename —— 設定檔位置由程式決定，瀏覽器不能指定。"""
    schemas = (ROOT / "shop" / "schemas.py").read_text(encoding="utf-8")
    block = re.search(
        r"class AiSettingsUpdate\(BaseModel\):(.*?)(?=\nclass |\Z)", schemas, re.S
    )
    assert block, "找不到 AiSettingsUpdate"
    fields = set(re.findall(r"^\s{4}(\w+):", block.group(1), re.M))
    assert fields == {"model", "api_key", "provider", "base_url"}, f"請求模型多了欄位：{fields}"

    settings_source = (ROOT / "shop" / "settings.py").read_text(encoding="utf-8")
    for forbidden in ("config_path:", "filename:", "path: str", "Request.body"):
        assert forbidden not in settings_source, forbidden


# ----------------------------------------------------------------------
# 13-14. 與 analyze_item 共用同一份設定
# ----------------------------------------------------------------------


def test_analyze_item_reads_the_same_file(local, seeded):
    """設定頁寫進去的檔案，adapter 要讀得到同一份。"""
    local.post("/api/settings/ai", json={"model": "shared/model:free",
                                         "api_key": NEW_SECRET})
    config = ai_config.load_config(seeded)
    assert config.model == "shared/model:free"
    assert config.api_key == NEW_SECRET
    assert config.provider == "openrouter"
    assert config.base_url == ai_config.DEFAULT_BASE_URL


def test_adapter_and_server_share_one_implementation():
    """設定語意只有一份，不複製。"""
    adapter = (ROOT / "tools" / "analyze_item.py").read_text(encoding="utf-8")
    assert "from shop.ai_config import" in adapter
    assert "from shop.ai_client import" in adapter
    assert "def load_config(" not in adapter, "adapter 不該自己刻一份 load_config"
    assert "def redact(" not in adapter, "adapter 不該自己刻一份 redact"
    assert "class AiConfig" not in adapter
    assert "def call_ai_provider(" not in adapter, "adapter 不該自己刻一份 client"
    assert "def build_request_body(" not in adapter, "adapter 不該自己刻一份 request builder"


def test_api_does_not_contain_its_own_config_format():
    """server 端也不該複製一份讀寫邏輯。"""
    settings_source = (ROOT / "shop" / "settings.py").read_text(encoding="utf-8")
    assert "def read_settings(" not in settings_source
    assert "def save_settings(" not in settings_source
    assert "ai_config.read_settings()" in settings_source
    assert "ai_config.save_settings(" in settings_source

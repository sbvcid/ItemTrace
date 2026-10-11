"""手機配對（免設定檔配對）的端到端與安全邊界。

這是三層授權模型（admin／device／unpaired；shop/security.py）與配對流程
（shop/pairing.py）的回歸基礎。原設計的手機端 Ed25519 簽章在區網 HTTP
不是 secure context、`crypto.subtle` 不可用，已改為「一次性配對碼 →
裝置權杖」：對應舊測試項目的「無效簽章」＝ 錯誤的配對碼。

真機瀏覽器無法在 CI 執行；前端行為以靜態檢查（不得使用外部 QR 服務、
不得有 inline 事件處理器）與後端契約測試釘住，真機驗收範圍見交付報告。
"""

from __future__ import annotations

import dataclasses
import ipaddress
import json
import re
import socket
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from shop import config as config_mod, db as db_mod, pairing as pairing_mod
from shop.repo import Repository
from tests.conftest import LAN_ADDRESS, LOOPBACK_ADDRESS, make_jpeg, pair_test_device

TEST_HEADERS = {"X-Requested-With": "ItemTrace"}
ROOT = Path(__file__).resolve().parents[1]


def _client(config, address, headers=None):
    from fastapi.testclient import TestClient

    from shop.api import create_app

    return TestClient(
        create_app(config),  # 每次建立＝新的 app 實例（相當於重啟）
        client=tuple(address),
        base_url="http://localhost",
        headers={**TEST_HEADERS, **(headers or {})},
    )


def _admin(config):
    """電腦本機（loopback）。"""
    return _client(config, LOOPBACK_ADDRESS)


def _lan(config):
    """未配對的區網裝置（沒有裝置憑證）。"""
    return _client(config, LAN_ADDRESS)


def _device(config, token):
    """已配對手機（Bearer 權杖；cookie 版本由 claim 流程本身驗證）。"""
    return _client(config, LAN_ADDRESS, {"Authorization": f"Bearer {token}"})


def _new_session(config, ttl_seconds=300):
    """建立一個配對工作階段（走與 HTTP 相同的 repo 方法）。"""
    with Repository.open(config) as repo:
        session_id, code, _expires = repo.create_pairing_session(
            "http://192.168.50.23:8731/pair#id={session_id}&code={code}",
            ttl_seconds=ttl_seconds,
        )
    return session_id, code


def _wrong_code(code: str) -> str:
    return "000000" if code != "000000" else "111111"


@pytest.fixture()
def fake_lan_ip(monkeypatch):
    """固定區網位址偵測，讓配對網址可預期（不碰真實網卡）。"""
    monkeypatch.setattr(
        pairing_mod, "local_ipv4_addresses", lambda: ["192.168.50.23"]
    )


# ----------------------------------------------------------------------
# 1. 配對工作階段：建立、狀態、過期、錯誤碼、重複使用、暴力嘗試
# ----------------------------------------------------------------------


def test_start_creates_short_lived_session_with_openable_url(config, fake_lan_ip):
    with _admin(config) as c:
        response = c.post("/api/pairing/start")
    assert response.status_code == 200
    body = response.json()
    assert re.fullmatch(r"\d{6}", body["code"])
    # QR Code 內容是手機瀏覽器可直接開啟的網址（不是純文字 JSON），
    # 且配對碼與工作階段 id 只放在 fragment：不會進入 HTTP 請求行。
    assert body["pairing_url"] == (
        f"http://192.168.50.23:8731/pair"
        f"#id={body['session_id']}&code={body['code']}"
    )
    parsed = urlsplit(body["pairing_url"])
    assert parsed.path == "/pair"
    assert parsed.query == ""
    assert body["code"] not in parsed.path
    assert body["session_id"] not in parsed.path
    assert f"code={body['code']}" in parsed.fragment

    with Repository.open(config) as repo:
        session = repo.get_pairing_session(body["session_id"])
    assert session is not None
    ttl = datetime.fromisoformat(session.expires_at) - datetime.fromisoformat(
        session.created_at
    )
    assert 0 < ttl.total_seconds() <= pairing_mod.PAIRING_TTL_SECONDS
    assert session.attempts == 0 and session.claimed_at is None


def test_session_status_reflects_claim(config):
    session_id, code = _new_session(config)
    with _admin(config) as admin:
        before = admin.get(f"/api/pairing/sessions/{session_id}")
        assert before.status_code == 200
        assert before.json()["claimed"] is False

    with _lan(config) as phone:
        claim = phone.post(
            "/api/pairing/claim",
            json={"session_id": session_id, "code": code, "device_name": "我的手機"},
        )
        assert claim.status_code == 200

    with _admin(config) as admin:
        after = admin.get(f"/api/pairing/sessions/{session_id}").json()
    assert after["claimed"] is True
    assert after["device_name"] == "我的手機"


def test_claim_with_wrong_code_is_rejected_and_counted(config):
    session_id, good_code = _new_session(config)
    with _lan(config) as phone:
        response = phone.post(
            "/api/pairing/claim",
            json={"session_id": session_id, "code": _wrong_code(good_code)},
        )
    assert response.status_code == 400
    assert "還可嘗試" in response.json()["detail"]
    with Repository.open(config) as repo:
        assert repo.get_pairing_session(session_id).attempts == 1


def test_claim_unknown_session_is_rejected(config):
    with _lan(config) as phone:
        response = phone.post(
            "/api/pairing/claim",
            json={"session_id": "01NO-SUCH-SESSION", "code": "123456"},
        )
    assert response.status_code == 400


def test_claim_after_expiry_is_rejected(config):
    session_id, code = _new_session(config, ttl_seconds=-1)
    with _lan(config) as phone:
        response = phone.post(
            "/api/pairing/claim",
            json={"session_id": session_id, "code": code},
        )
    assert response.status_code == 400
    assert "過期" in response.json()["detail"]


def test_claimed_session_cannot_be_reused(config):
    session_id, code = _new_session(config)
    claim = {"session_id": session_id, "code": code, "device_name": "第一次"}
    with _lan(config) as phone:
        first = phone.post("/api/pairing/claim", json=claim)
        assert first.status_code == 200
        second = phone.post("/api/pairing/claim", json=claim)
    assert second.status_code == 409
    assert "已使用" in second.json()["detail"]


def test_brute_force_is_limited_and_locks_the_session(config):
    session_id, good_code = _new_session(config)
    with _lan(config) as phone:
        for _ in range(pairing_mod.PAIRING_MAX_ATTEMPTS):
            response = phone.post(
                "/api/pairing/claim",
                json={"session_id": session_id, "code": _wrong_code(good_code)},
            )
            assert response.status_code == 400
        # 已達上限：連正確的碼也不再受理（工作階段失效）。
        locked = phone.post(
            "/api/pairing/claim",
            json={"session_id": session_id, "code": good_code},
        )
    assert locked.status_code == 400
    assert "嘗試次數過多" in locked.json()["detail"]
    with Repository.open(config) as repo:
        session = repo.get_pairing_session(session_id)
    assert session.attempts >= pairing_mod.PAIRING_MAX_ATTEMPTS
    assert session.claimed_at is None


# ----------------------------------------------------------------------
# 2＆8. 成功配對後的手機存取；本機管理不受影響
# ----------------------------------------------------------------------


def test_paired_device_can_use_normal_data_apis(config):
    _device_id, _name, token = pair_test_device(config)
    with _device(config, token) as phone:
        assert phone.get("/api/items").status_code == 200
        created = phone.post("/api/items", json={"name": "手機建立"})
        assert created.status_code == 201
        item_id = created.json()["id"]
        assert phone.get(f"/api/items/{item_id}").status_code == 200
        # 照片上傳（未建檔的 inbox 流程）也可用。
        upload = phone.post(
            "/api/inbox/photos",
            files=[("files", ("p.jpg", make_jpeg(), "image/jpeg"))],
        )
        assert upload.status_code == 201
        # AI 端點可達：沒有照片是業務錯誤（400），不是授權錯誤。
        assert phone.post(f"/api/items/{item_id}/ai/analyze").status_code == 400


def test_paired_device_can_read_media_via_cookie_without_header(config):
    """手機的 <img src="/files/…"> 不帶 Authorization；配對時下的
    HttpOnly cookie 讓媒體請求也能通過裝置認證。"""
    with _admin(config) as admin:
        upload = admin.post(
            "/api/inbox/photos",
            files=[("files", ("media.jpg", make_jpeg(), "image/jpeg"))],
        )
        relative = upload.json()["staged"][0]

    session_id, code = _new_session(config)
    with _lan(config) as phone:
        assert phone.get(f"/files/{relative}").status_code == 403  # 未配對
        claim = phone.post(
            "/api/pairing/claim", json={"session_id": session_id, "code": code}
        )
        assert claim.status_code == 200
        assert "itemtrace_device" in phone.cookies
        # 完全沒有 Authorization 標頭，只有 cookie。
        assert phone.get(f"/files/{relative}").status_code == 200
        assert phone.get("/api/items").status_code == 200


def test_pairing_survives_server_restart(config):
    """每個 _client 都是新的 app 實例（同一份資料庫）＝ 服務重啟；
    已配對裝置的權杖必須續用，不需要重新配對。"""
    device_id, name, token = pair_test_device(config, "重啟測試機")
    with _client(config, LAN_ADDRESS, {"Authorization": f"Bearer {token}"}) as restarted:
        assert restarted.get("/api/items").status_code == 200
        body = restarted.get("/api/session").json()
    assert body["role"] == "device"
    assert body["device_id"] == device_id
    assert body["device_name"] == name


def test_local_admin_flow_unchanged(config):
    """電腦本機（loopback）照舊完整可用 —— 不因配對授權而受限。"""
    with _admin(config) as admin:
        assert admin.get("/api/items").status_code == 200
        assert admin.post("/api/items", json={"name": "本機建立"}).status_code == 201
        assert admin.get("/api/settings/ai").status_code == 200
        assert admin.get("/api/session").json()["role"] == "admin"


# ----------------------------------------------------------------------
# 3＆4. 未配對一律拒絕；撤銷後原憑證立即失效
# ----------------------------------------------------------------------


def test_unpaired_lan_cannot_read_or_write_private_data(config):
    """未配對裝置不會因為「GET 是安全方法」「帶了 CSRF 標頭」而取得資料。"""
    with _lan(config) as c:  # 所有請求都帶 X-Requested-With: ItemTrace
        assert c.get("/api/items").status_code == 403
        assert c.post("/api/items", json={"name": "x"}).status_code == 403
        assert c.get("/api/items/ITM-0001").status_code == 403
        assert c.get("/api/stats").status_code == 403
        assert c.get("/api/settings/ai").status_code == 403
        assert c.get("/api/templates").status_code == 403
        assert c.get("/files/whatever.jpg").status_code == 403
        assert c.get("/api/session").json()["role"] == "unpaired"


def test_unpaired_lan_only_gets_pairing_essentials(config):
    """未配對裝置仍可載入配對頁與完成配對所需的端點。"""
    with _lan(config) as c:
        # QR 網址的參數在 fragment；瀏覽器送出的就是這個裸路徑。
        assert c.get("/pair").status_code == 200
        assert c.get("/app.js").status_code == 200
        assert c.get("/app.css").status_code == 200
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/session").status_code == 200


def test_revoked_token_is_rejected_everywhere(config):
    device_id, _name, token = pair_test_device(config)
    with _admin(config) as admin:
        assert admin.delete(f"/api/pairing/devices/{device_id}").status_code == 204
    with _device(config, token) as phone:
        assert phone.get("/api/items").status_code == 401
        assert phone.get("/api/settings/ai").status_code == 401
        assert phone.get("/files/x.jpg").status_code == 401
        assert phone.post("/api/items", json={"name": "x"}).status_code == 401
        assert phone.get("/api/session").json()["role"] == "unpaired"


def test_revoked_cookie_is_rejected(config):
    session_id, code = _new_session(config)
    with _lan(config) as phone:
        claim = phone.post(
            "/api/pairing/claim", json={"session_id": session_id, "code": code}
        )
        assert claim.status_code == 200
        assert phone.get("/api/items").status_code == 200
        with _admin(config) as admin:
            admin.delete(f"/api/pairing/devices/{claim.json()['device_id']}")
        # 即使 cookie 還在瀏覽器上，撤銷後一律失效。
        assert phone.get("/api/items").status_code == 401
        assert phone.get(f"/files/x.jpg").status_code == 401


def test_revocation_is_idempotent(config):
    device_id, _name, _token = pair_test_device(config)
    with _admin(config) as admin:
        assert admin.delete(f"/api/pairing/devices/{device_id}").status_code == 204
        assert admin.delete(f"/api/pairing/devices/{device_id}").status_code == 204


# ----------------------------------------------------------------------
# 5. 配對管理端點：只有電腦本機可呼叫
# ----------------------------------------------------------------------


def test_admin_pairing_endpoints_reject_unpaired_lan(config, fake_lan_ip):
    session_id, _code = _new_session(config)
    with _lan(config) as c:
        assert c.post("/api/pairing/start").status_code == 403
        assert c.get("/api/pairing/devices").status_code == 403
        assert c.delete("/api/pairing/devices/DEV-ANY").status_code == 403
        assert c.get(f"/api/pairing/sessions/{session_id}").status_code == 403
        assert (
            c.get(f"/api/pairing/sessions/{session_id}/qr.svg").status_code == 403
        )


def test_admin_pairing_endpoints_reject_paired_device(config, fake_lan_ip):
    """已配對手機可以存取資料，但**不能**管理配對（含撤銷自己）。"""
    device_id, _name, token = pair_test_device(config)
    with _device(config, token) as phone:
        assert phone.post("/api/pairing/start").status_code == 403
        assert phone.get("/api/pairing/devices").status_code == 403
        assert phone.delete(f"/api/pairing/devices/{device_id}").status_code == 403


def test_device_list_never_exposes_credentials(config):
    device_id, name, token = pair_test_device(config, "秘密測試機")
    with _admin(config) as admin:
        response = admin.get("/api/pairing/devices")
    assert response.status_code == 200
    raw = response.text
    assert token not in raw
    assert pairing_mod.hash_device_token(token) not in raw
    entry = response.json()[0]
    assert entry["id"] == device_id and entry["name"] == name
    assert "token" not in entry and "token_hash" not in entry
    assert "public_key" not in entry


def test_session_endpoint_reports_roles(config):
    with _admin(config) as admin:
        assert admin.get("/api/session").json()["role"] == "admin"
    with _lan(config) as lan:
        assert lan.get("/api/session").json()["role"] == "unpaired"


# ----------------------------------------------------------------------
# 6. QR Code：可開啟的網址、本機產生、不送第三方
# ----------------------------------------------------------------------


def test_qr_is_served_locally_as_svg(config, fake_lan_ip):
    with _admin(config) as admin:
        start = admin.post("/api/pairing/start").json()
        response = admin.get(
            f"/api/pairing/sessions/{start['session_id']}/qr.svg"
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in response.content
    # 內容是圖形編碼，不是明文資料傾印；也不含任何外部服務 URL。
    assert start["pairing_url"].encode() not in response.content
    assert b"qrserver" not in response.content


def test_qr_svg_is_a_standalone_renderable_document(config, fake_lan_ip):
    """迴歸：QR SVG 必須是獨立、可被瀏覽器解碼的文件。

    災情：原本用 segno 的 ``svg_inline()``（內嵌 HTML 用的片段，沒有
    SVG namespace 與 viewBox）。``<img src="/…/qr.svg">`` 拿到 HTTP 200
    但瀏覽器無法解碼（實測 naturalWidth = 0），設定頁的 QR 一片空白。
    """
    from xml.dom import minidom

    with _admin(config) as admin:
        start = admin.post("/api/pairing/start").json()
        response = admin.get(
            f"/api/pairing/sessions/{start['session_id']}/qr.svg"
        )
    assert response.status_code == 200
    body = response.content
    assert body.startswith(b"<?xml"), "獨立 SVG 應有 XML 宣告"
    assert b'xmlns="http://www.w3.org/2000/svg"' in body, "缺 namespace 瀏覽器無法解碼"
    assert b"viewBox=" in body, "<img> 縮放需要 viewBox"
    # 必須是格式正確的 XML（解碼失敗曾是實際災情）。
    document = minidom.parseString(body)
    assert document.documentElement.tagName == "svg"


def test_pairing_copy_matches_the_real_button():
    """zh-TW 文案必須跟畫面上的按鈕一致：沒有「連結手機」，用「開始配對」。"""
    zh = (ROOT / "web" / "i18n" / "zh-TW.js").read_text(encoding="utf-8")
    assert "連結手機" not in zh
    assert "開始配對" in zh
    en = (ROOT / "web" / "i18n" / "en.js").read_text(encoding="utf-8")
    assert "連結手機" not in en
    # 整個前端都不該再出現舊按鈕名稱。
    for path in (ROOT / "web").rglob("*.js"):
        assert "連結手機" not in path.read_text(encoding="utf-8"), path


def test_settings_view_shows_pairing_failures_with_retry():
    """前端必須有明確的失敗處理：可讀訊息＋QR 重試，不能只留空白或破圖。"""
    source = (ROOT / "web" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "pairing-start-error" in source, "建立工作階段失敗要保留可讀訊息"
    assert "pairing-qr-error" in source, "QR 載入失敗要顯示原因區塊"
    assert "btn-retry-qr" in source, "QR 載入失敗要提供重試"
    assert "addEventListener('error'" in source, "要監聽 QR 圖片載入失敗"


def test_qr_generation_never_uses_the_network(config, fake_lan_ip, monkeypatch):
    """QR 產生期間任何 socket 連線都直接失敗 —— 證明是純本機產生。"""
    with _admin(config) as admin:
        start = admin.post("/api/pairing/start").json()

        def _blocked(*_args, **_kwargs):
            raise AssertionError("QR Code 產生不得連網")

        monkeypatch.setattr(socket.socket, "connect", _blocked)
        monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
        response = admin.get(
            f"/api/pairing/sessions/{start['session_id']}/qr.svg"
        )
    assert response.status_code == 200


def test_build_pairing_url_keeps_secrets_in_fragment():
    """fragment 不進 HTTP 請求：配對碼與工作階段 id 都不在 path／query。"""
    url = pairing_mod.build_pairing_url("192.168.1.5", 8731, "01SESSION", "123456")
    assert url == "http://192.168.1.5:8731/pair#id=01SESSION&code=123456"
    parsed = urlsplit(url)
    assert parsed.path == "/pair"
    assert parsed.query == ""
    assert "123456" not in parsed.path and "01SESSION" not in parsed.path
    assert "id=01SESSION" in parsed.fragment and "code=123456" in parsed.fragment


def test_pairing_code_never_appears_in_the_http_request(config, fake_lan_ip):
    """手機開啟 QR 網址時瀏覽器只送出 path（fragment 留在瀏覽器端）：

    配對碼不會出現在 Uvicorn access log 記下的請求行；配對頁仍可開啟、
    配對仍能完成。"""
    with _admin(config) as admin:
        start = admin.post("/api/pairing/start").json()

    # 模擬瀏覽器實際送出的請求目標：path（＋query，本例為空）。
    parsed = urlsplit(start["pairing_url"])
    request_target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    assert start["code"] not in request_target
    assert start["session_id"] not in request_target

    with _lan(config) as phone:
        assert phone.get(request_target).status_code == 200  # 配對頁可開啟
        # 手機從 fragment 讀到 id/code 後完成配對。
        claim = phone.post(
            "/api/pairing/claim",
            json={
                "session_id": start["session_id"],
                "code": start["code"],
                "device_name": "Fragment Phone",
            },
        )
        assert claim.status_code == 200
        assert phone.get("/api/items").status_code == 200


def test_pairing_page_reads_code_from_fragment():
    source = (ROOT / "web" / "views" / "pair.js").read_text(encoding="utf-8")
    assert "location.hash" in source, "配對頁必須從 fragment 讀取配對碼"


def test_frontend_has_no_external_qr_service():
    """前端不得把配對資料送往第三方 QR 服務（曾誤用 api.qrserver.com）。"""
    web = ROOT / "web"
    offenders = []
    for path in web.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        if "qrserver" in text or "chart.googleapis" in text:
            offenders.append(path.relative_to(web).as_posix())
    assert offenders == [], f"發現外部 QR 服務：{offenders}"


def test_pairing_uses_local_library_and_stdlib_only():
    source = (ROOT / "shop" / "pairing.py").read_text(encoding="utf-8")
    assert "import segno" in source
    assert "urllib" not in source and "requests" not in source


def test_pairing_code_and_token_hash_round_trip():
    code = pairing_mod.generate_pairing_code()
    assert re.fullmatch(r"\d{6}", code)
    token = pairing_mod.generate_device_token()
    assert len(token) >= 32
    digest = pairing_mod.hash_device_token(token)
    assert digest == pairing_mod.hash_device_token(token)
    assert token not in digest
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_detected_lan_addresses_never_include_loopback():
    for candidate in pairing_mod.local_ipv4_addresses():
        address = ipaddress.ip_address(candidate)
        assert not address.is_loopback
        assert not address.is_unspecified


def test_start_fails_clearly_when_no_lan_address(config, monkeypatch):
    monkeypatch.setattr(pairing_mod, "local_ipv4_addresses", lambda: [])
    with _admin(config) as admin:
        response = admin.post("/api/pairing/start")
    assert response.status_code == 400
    assert "區網" in response.json()["detail"]


# ----------------------------------------------------------------------
# 7. 啟動不需要手動修改 config.json
# ----------------------------------------------------------------------


def test_default_config_is_lan_ready_without_editing(tmp_path):
    """全新環境（沒有 config.json）啟動即具備手機連線能力。"""
    cfg = config_mod.load(tmp_path)
    assert cfg.server_host == "0.0.0.0"
    assert "allow_lan" not in config_mod.DEFAULTS
    from serve import resolve_bind_host

    assert resolve_bind_host(cfg, None) == "0.0.0.0"


def test_serve_warns_when_explicit_loopback_blocks_phones(config):
    from serve import resolve_bind_host

    loopback_only = dataclasses.replace(config, server_host="127.0.0.1")
    assert resolve_bind_host(loopback_only, None) == "127.0.0.1"


def test_legacy_config_file_still_allows_pairing(tmp_path, monkeypatch):
    """迴歸：舊版設定檔（server_host: "127.0.0.1"）不得讓手機配對意外
    失效 —— load() 自動升級為區網綁定，start 能產生可掃描的配對網址。"""
    (tmp_path / "config.json").write_text(
        json.dumps({"server_host": "127.0.0.1"}), encoding="utf-8"
    )
    cfg = config_mod.load(tmp_path)
    assert cfg.server_host == "0.0.0.0"  # 舊預設值自動升級，不需手改設定

    monkeypatch.setattr(
        pairing_mod, "local_ipv4_addresses", lambda: ["192.168.50.23"]
    )
    db_mod.init(cfg)
    config_mod.ensure_dirs(cfg)
    with _admin(cfg) as admin:
        response = admin.post("/api/pairing/start")
    assert response.status_code == 200
    assert response.json()["pairing_url"].startswith(
        "http://192.168.50.23:8731/pair#"
    )


def test_local_only_mode_binds_loopback_and_explains_the_pairing_block(tmp_path):
    """純本機模式是真的模式：綁 loopback、本機功能照常，配對端點給出
    可操作的解除說明（不是把既有模式整個弄壞、也不是只改訊息）。"""
    (tmp_path / "config.json").write_text(
        json.dumps({"local_only": True}), encoding="utf-8"
    )
    cfg = config_mod.load(tmp_path)
    assert cfg.local_only is True
    assert cfg.server_host == "127.0.0.1"

    from serve import resolve_bind_host

    assert resolve_bind_host(cfg, None) == "127.0.0.1"

    db_mod.init(cfg)
    config_mod.ensure_dirs(cfg)
    with _admin(cfg) as admin:
        assert admin.get("/api/items").status_code == 200  # 本機功能不受影響
        response = admin.post("/api/pairing/start")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "local_only" in detail and "false" in detail


# ----------------------------------------------------------------------
# 資料庫：舊形狀（公鑰模型）的最小遷移
# ----------------------------------------------------------------------


def test_db_init_migrates_legacy_paired_devices_table(tmp_path):
    cfg = config_mod.load(tmp_path)
    conn = sqlite3.connect(cfg.database)
    conn.execute(
        """
        CREATE TABLE paired_devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            public_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_seen_at TEXT,
            revoked_at TEXT
        ) STRICT
        """
    )
    conn.execute(
        "INSERT INTO paired_devices VALUES ('DEV-OLD', 'old', 'pk', 't', NULL, NULL)"
    )
    conn.commit()
    conn.close()

    db_mod.init(cfg)  # 重新 init：舊表只存配對憑證，直接重建

    conn = sqlite3.connect(cfg.database)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(paired_devices)")}
        rows = conn.execute("SELECT count(*) FROM paired_devices").fetchone()[0]
        session_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(pairing_sessions)")
        }
    finally:
        conn.close()
    assert "token_hash" in columns
    assert "public_key" not in columns
    assert rows == 0
    assert {"id", "code", "expires_at", "attempts", "claimed_at"} <= session_cols

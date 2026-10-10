"""SR-2 安全強化回歸測試（SECURITY-AUDIT F4／F7／F8）。

全部走隔離實例：tmp DATA_ROOT、合成資料；不發任何真實網路請求
（provider 一律 monkeypatch）。列印相關測試需要 Chromium，缺瀏覽器／
PyMuPDF 時與 tests/test_print.py 同一慣例 skip。

SR-1 的既有保護（Host/Origin/標頭、key 不轉送、綁定、媒體）仍由
tests/test_security.py 全套回歸，這裡不重複。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import struct

import pytest

from shop import ai_client, ai_config, limits, print_backend
from shop.errors import ValidationError
from shop.limits import SlidingWindowLimiter
from shop.template_renderer import (
    RenderError,
    TemplateRenderer,
    TemplateViewModel,
    render_template,
    render_template_preview,
)
from shop.template_validator import MAX_TEMPLATE_BYTES, validate_template
from tests.conftest import make_jpeg

TEST_HEADERS = {"X-Requested-With": "ItemTrace"}


def _client_for(app_config, **kwargs):
    from fastapi.testclient import TestClient

    from shop.api import create_app

    return TestClient(
        create_app(app_config), base_url="http://localhost", headers=TEST_HEADERS, **kwargs
    )


def _empty_view_model() -> TemplateViewModel:
    return TemplateViewModel(
        id="1", name="", brand="", model="", category="",
        quantity="1", condition="", notes="", primary_photo="",
    )


def _render_with_renderer(template_html: str) -> str:
    renderer = TemplateRenderer(_empty_view_model())
    renderer.feed(template_html)
    renderer.close()
    return renderer.render()


def _png_header(width: int, height: int) -> bytes:
    """合法 PNG 簽章＋IHDR 標頭（不用真圖；image_dimensions 只看這裡）。"""
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


# ----------------------------------------------------------------------
# F4：HTTP body 上限
# ----------------------------------------------------------------------


def test_request_body_over_limit_is_rejected_before_routing(config):
    """Content-Length 超限：路由前 413，資料庫完全沒被碰。"""
    cfg = dataclasses.replace(config, max_request_bytes=4096)
    with _client_for(cfg) as c:
        response = c.post("/api/items", json={"name": "x" * 8000})
        assert response.status_code == 413
        assert "上限" in response.json()["detail"]
        assert c.get("/api/items").json() == []


def test_chunked_body_over_limit_is_rejected_by_stream_counting(config):
    """沒有 Content-Length 的 chunked 請求也擋（逐塊累計）。"""
    cfg = dataclasses.replace(config, max_request_bytes=4096)

    def chunks():
        yield b'{"name": "'
        yield b"y" * 8000
        yield b'"}'

    with _client_for(cfg) as c:
        response = c.post(
            "/api/items",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert c.get("/api/items").json() == []


# ----------------------------------------------------------------------
# F4：上傳單檔／檔數／像素上限
# ----------------------------------------------------------------------


def test_upload_file_over_limit_is_413_and_earlier_files_survive(config):
    """batch 中途超限：回 413，先前已成功的檔案留在 inbox（不靜默丟棄）。"""
    cfg = dataclasses.replace(config, max_upload_bytes=2048)
    small = make_jpeg()
    big = b"\xff\xd8" + b"\x00" * 5000
    with _client_for(cfg) as c:
        response = c.post(
            "/api/inbox/photos",
            files=[
                ("files", ("ok.jpg", small, "image/jpeg")),
                ("files", ("big.jpg", big, "image/jpeg")),
            ],
        )
        assert response.status_code == 413
        assert "單檔上限" in response.json()["detail"]
        entries = c.get("/api/inbox").json()["entries"]
        assert [e["relative"].endswith("ok.jpg") for e in entries] == [True]
        assert all(not e["relative"].endswith("big.jpg") for e in entries)


def test_observation_upload_over_limit_is_413_and_writes_nothing(config, repo):
    cfg = dataclasses.replace(config, max_upload_bytes=2048)
    item = repo.create_item(name="x")
    with _client_for(cfg) as c:
        observation = c.post(
            f"/api/items/{item.id}/observations", json={}
        ).json()
        response = c.post(
            f"/api/observations/{observation['id']}/photos",
            files=[("files", ("big.jpg", b"\xff\xd8" + b"\x00" * 5000, "image/jpeg"))],
        )
        assert response.status_code == 413
        detail = c.get(f"/api/items/{item.id}").json()
        assert detail["photos"] == []


def test_upload_file_count_limit_rejects_without_saving_anything(config):
    cfg = dataclasses.replace(config, max_upload_files=2)
    files = [
        ("files", (f"p{index}.jpg", make_jpeg(), "image/jpeg"))
        for index in range(3)
    ]
    with _client_for(cfg) as c:
        response = c.post("/api/inbox/photos", files=files)
        assert response.status_code == 400
        assert "最多 2 個檔案" in response.json()["detail"]
        assert c.get("/api/inbox").json()["count"] == 0


def test_decompression_bomb_like_jpeg_is_rejected_by_pixel_cap(config):
    """小檔案、宣稱 20000x20000 的 JPEG：上傳時 400，不進任何儲存。"""
    bomb = make_jpeg(width=20000, height=20000)
    assert len(bomb) < 2048, "fixture 必須是『小檔大像素』"
    with _client_for(config) as c:
        response = c.post(
            "/api/inbox/photos",
            files=[("files", ("bomb.jpg", bomb, "image/jpeg"))],
        )
        assert response.status_code == 400
        assert "像素" in response.json()["detail"]
        assert c.get("/api/inbox").json()["count"] == 0


def test_png_pixel_cap_is_read_from_the_header():
    data = _png_header(30000, 30000)  # 900 MP
    assert limits.image_dimensions(data) == (30000, 30000)
    with pytest.raises(ValidationError):
        limits.check_image_pixels(data, "bomb.png")
    ok = _png_header(4000, 3000)  # 12 MP
    assert limits.image_dimensions(ok) == (4000, 3000)
    limits.check_image_pixels(ok, "ok.png")  # 不拋出


# ----------------------------------------------------------------------
# F4：AI 呼叫節流
# ----------------------------------------------------------------------


@pytest.fixture()
def ai_config_file(tmp_path, monkeypatch):
    path = tmp_path / "ai_config.local.json"
    path.write_text(
        json.dumps({
            "api_key": "sk-or-v1-TEST-SR2-0000000000",
            "model": "test/model",
            "provider": "openrouter",
            "base_url": ai_config.DEFAULT_BASE_URL,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_config, "config_path", lambda *a, **k: path)
    return path


@pytest.fixture()
def fake_provider(monkeypatch):
    calls: list[dict] = []

    def fake(api_key, model, data_urls, *, provider=None, base_url=None,
             timeout=None, context=""):
        calls.append({"model": model})
        return {"choices": [{"message": {"content": json.dumps({"suggestions": []})}}]}

    monkeypatch.setattr(ai_client, "call_ai_provider", fake)
    return calls


def _add_item_with_photo(repo, config):
    item = repo.create_item()
    data = make_jpeg()
    destination = config.files_dir / item.id / "original" / "IMG.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    repo.add_photo(
        item.id, f"files/{item.id}/original/IMG.jpg",
        orig_name="IMG.jpg",
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data), role="original",
    )
    return item


def test_analyze_rate_limit_returns_429_and_stops_provider_calls(
    config, repo, ai_config_file, fake_provider
):
    cfg = dataclasses.replace(config, analyze_per_minute=2)
    item = _add_item_with_photo(repo, cfg)
    with _client_for(cfg) as c:
        assert c.post(f"/api/items/{item.id}/ai/analyze").status_code == 201
        assert c.post(f"/api/items/{item.id}/ai/analyze").status_code == 201
        third = c.post(f"/api/items/{item.id}/ai/analyze")
    assert third.status_code == 429
    assert "Retry-After" in third.headers
    assert "過於頻繁" in third.json()["detail"]
    # 第 3 次沒有打到 provider（節流擋在真正昂貴的事情之前）。
    assert len(fake_provider) == 2


def test_analyze_limiter_window_slides():
    clock = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: clock[0])
    assert limiter.consume() is True
    assert limiter.consume() is True
    assert limiter.consume() is False
    assert limiter.retry_after() == 60

    clock[0] = 30.0
    assert limiter.consume() is False  # 兩個事件都還在視窗內

    clock[0] = 60.5
    assert limiter.consume() is True  # 第一筆已過期，額度釋放
    assert limiter.retry_after() == 0


def test_analyze_limiter_zero_means_disabled():
    limiter = SlidingWindowLimiter(limit=0, window_seconds=60, clock=lambda: 0.0)
    assert all(limiter.consume() for _ in range(100))
    assert limiter.retry_after() == 0


# ----------------------------------------------------------------------
# F4：列印尺寸上限
# ----------------------------------------------------------------------


def test_print_size_cap_is_rejected_before_browser(monkeypatch):
    """超大 Template 尺寸：400 且完全不啟動 Chromium。"""
    monkeypatch.setattr(
        print_backend, "find_browser",
        lambda: pytest.fail("不該啟動瀏覽器：尺寸上限必須先擋"),
    )
    with pytest.raises(ValidationError) as exc:
        print_backend.build_pdf(
            "<html><body>x</body></html>",
            width_mm=5000, height_mm=5000, unit="mm",
        )
    assert "列印尺寸過大" in str(exc.value)


def test_print_html_size_cap_never_reaches_printer(monkeypatch):
    monkeypatch.setattr(
        print_backend, "find_browser",
        lambda: pytest.fail("不該啟動瀏覽器：尺寸上限必須先擋"),
    )
    monkeypatch.setattr(
        print_backend, "_send_to_printer",
        lambda *a, **k: pytest.fail("不該送印表機"),
    )
    with pytest.raises(ValidationError):
        print_backend.print_html(
            "<html><body>x</body></html>",
            template_id="TPL-1", item_id="ITM-1",
            width_mm=9000, height_mm=9000, unit="mm",
        )


def test_template_size_cap():
    with pytest.raises(ValidationError) as exc:
        validate_template("x" * (MAX_TEMPLATE_BYTES + 1))
    assert "Template 過大" in str(exc.value)


def test_inline_photos_skips_non_raster_types():
    html = '<img src="/files/ITM-1/original/evil.svg"><img src="/files/ITM-1/original/a.jpg">'
    out = print_backend.inline_photos(html, lambda relative: b"X")
    assert "/files/ITM-1/original/evil.svg" in out  # 不 inline 可疑型別
    assert "data:" in out                            # raster 照常


# ----------------------------------------------------------------------
# F7：API 文件預設關閉
# ----------------------------------------------------------------------


def test_docs_and_openapi_are_disabled_by_default(client):
    for path in ("/docs", "/openapi.json", "/redoc"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "停用" in response.json()["detail"]
    # SPA 本身不受影響
    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_docs_enabled_explicitly(config):
    cfg = dataclasses.replace(config, enable_docs=True)
    with _client_for(cfg) as c:
        assert c.get("/docs").status_code == 200
        assert "/api/items" in c.get("/openapi.json").json()["paths"]


# ----------------------------------------------------------------------
# F7：快取政策
# ----------------------------------------------------------------------


def test_api_responses_are_no_store(client):
    response = client.get("/api/items")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"


def test_static_assets_keep_normal_caching(client):
    response = client.get("/app.js")
    assert response.status_code == 200
    assert "no-store" not in response.headers.get("cache-control", "")


def test_photos_are_private_cache(client):
    response = client.post(
        "/api/inbox/photos",
        files=[("files", ("photo.jpg", make_jpeg(), "image/jpeg"))],
    )
    assert response.status_code == 201
    relative = response.json()["entries"][0]["relative"]
    served = client.get(f"/files/{relative}")
    assert served.status_code == 200
    header = served.headers.get("cache-control", "")
    assert "private" in header
    assert "public" not in header


# ----------------------------------------------------------------------
# F7：錯誤訊息不洩漏檔案系統路徑／設定內容
# ----------------------------------------------------------------------


def test_file_404_does_not_disclose_data_root(client, config):
    response = client.get("/files/files/ITM-9999/original/nope.jpg")
    assert response.status_code == 404
    assert str(config.data_root) not in response.text
    assert str(config.base_dir) not in response.text


def test_config_error_details_stay_on_the_server(capsys):
    from shop.api import _detail
    from shop.config import ConfigError

    secret_path = r"C:\very\private\place\config.json"
    detail = _detail(ConfigError(f"{secret_path} 不在資料根目錄內"))

    assert isinstance(detail, str)
    assert secret_path not in detail
    assert "設定錯誤" in detail
    # 完整原因只印在伺服器 console
    assert secret_path in capsys.readouterr().err


# ----------------------------------------------------------------------
# F8：Template 渲染的 mXSS 防線
# ----------------------------------------------------------------------


def test_validator_rejects_comments_with_markup():
    """`<!-->` 立即結束註解：Python 與瀏覽器解讀不同 → 存檔就擋。"""
    with pytest.raises(ValidationError) as exc:
        validate_template("<html><body><!--><img src=x onerror=alert(1)>--></body></html>")
    assert "註解" in str(exc.value)


def test_renderer_drops_comments_entirely():
    """就算模板繞過驗證，renderer 也不會把註解內容送進瀏覽器。"""
    out = _render_with_renderer("<p>before<!--><img src=x onerror=alert(1)>-->after</p>")
    assert out == "<p>beforeafter</p>"
    assert "<img" not in out
    assert "onerror" not in out


def test_renderer_escapes_entity_encoded_markup():
    """`&lt;img …&gt;` 曾被解碼後原樣重送成真標籤；現在重新 escape。"""
    out = _render_with_renderer(
        '<p>&lt;img src=x onerror="alert(1)"&gt;</p>'
    )
    assert out == '<p>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;</p>'
    assert "<img" not in out

    script = _render_with_renderer("<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>")
    assert "<script" not in script
    assert "&lt;script&gt;" in script


def test_renderer_keeps_style_raw_text_intact():
    """CSS 的 `>`（子選擇器）不能被 escape，否則版面會壞。"""
    out = _render_with_renderer("<style>.a > .b { color: red; }</style><p>x</p>")
    assert ".a > .b { color: red; }" in out


def test_renderer_strips_event_and_unknown_attributes():
    out = _render_with_renderer(
        '<div onclick="x" class="c" data-unknown="y" ONMOUSEOVER="z">t</div>'
    )
    assert out == '<div class="c">t</div>'


def test_render_time_validation_blocks_direct_db_script_template(repo, client, config):
    """直接寫進 DB（繞過存檔驗證）的 <script> 模板：渲染／列印一律 400。"""
    template = repo.add_template(
        name="evil", html="<html><body><script>alert(1)</script></body></html>"
    )
    item = repo.create_item(name="x")

    preview = client.post(
        f"/api/templates/{template.id}/preview", json={"item_id": item.id}
    )
    assert preview.status_code == 400
    assert "驗證失敗" in preview.json()["detail"]

    printed = client.post(
        f"/api/templates/{template.id}/print-preview", json={"item_id": item.id}
    )
    assert printed.status_code == 400

    with pytest.raises(RenderError):
        render_template(template, item, repo, config)


def test_render_time_validation_blocks_direct_db_comment_payload(repo, client):
    template = repo.add_template(
        name="comment-payload",
        html="<html><body><!--><img src=x onerror=alert(1)>--><p>ok</p></body></html>",
    )
    item = repo.create_item(name="x")
    response = client.post(
        f"/api/templates/{template.id}/preview", json={"item_id": item.id}
    )
    assert response.status_code == 400


# ----------------------------------------------------------------------
# F8：Chromium 命令與真實列印管線（需要瀏覽器）
# ----------------------------------------------------------------------


def test_browser_command_sandbox_default_and_opt_out(monkeypatch, tmp_path):
    command = print_backend.build_browser_command(
        "chrome.exe", tmp_path / "a.pdf", tmp_path / "a.html"
    )
    assert "--no-sandbox" not in command
    assert command[1] == "--headless"
    assert any(part.startswith("--print-to-pdf=") for part in command)
    assert command[-1].startswith("file://")

    monkeypatch.setenv(print_backend.NO_SANDBOX_ENV, "1")
    opted_out = print_backend.build_browser_command(
        "chrome.exe", tmp_path / "a.pdf", tmp_path / "a.html"
    )
    assert "--no-sandbox" in opted_out


def _browser_and_pymupdf_or_skip():
    try:
        print_backend.find_browser()
    except print_backend.PrintUnavailableError as exc:
        pytest.skip(str(exc))
    try:
        import pymupdf
    except ImportError:
        pytest.skip("需要 PyMuPDF 才能驗證 PDF 內容")
    return pymupdf


def _pdf_text(pymupdf, pdf_bytes: bytes) -> str:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        return document[0].get_text()


def test_real_print_pipeline_does_not_execute_hostile_template_text(repo, config):
    """真實 Chromium 端到端 canary：修復前這兩個 payload 都會執行 JS。

    * entity 編碼的 `<img onerror>`（可過存檔驗證、先前 renderer 會解碼成
      真標籤）—— 走完整 render_template_preview 路徑。
    * `<!-->` 立即結束註解（先前 renderer 原樣輸出、Chromium 會把其中
      的 img 當真元素）—— 直接餵 renderer（模擬繞過驗證的模板），
      證明渲染層本身就安全。

    onerror 的內容會把 body 換成 SCRIPT-RAN：只要 PDF 文字仍有
    MARKER-OK 且沒有 SCRIPT-RAN，就證明腳本沒有執行。
    """
    pymupdf = _browser_and_pymupdf_or_skip()

    entity_payload = (
        '<html><body><div id="x">MARKER-OK</div>'
        "<p>&lt;img src=x onerror=\"document.body.innerHTML='SCRIPT-RAN'\"&gt;</p>"
        "</body></html>"
    )
    template = repo.add_template(
        name="canary-entity", html=entity_payload, width=100, height=150, unit="mm"
    )
    item = repo.create_item(name="canary")
    rendered = render_template_preview(template, item, repo, config)
    pdf, _, _ = print_backend.build_pdf(
        rendered, width_mm=100, height_mm=150, unit="mm"
    )
    text = _pdf_text(pymupdf, pdf)
    assert "MARKER-OK" in text
    assert "SCRIPT-RAN" not in text

    comment_payload = (
        '<html><body><div id="x">MARKER-OK</div>'
        "<p><!--><img src=x onerror=\"document.body.innerHTML='SCRIPT-RAN'\">--></p>"
        "</body></html>"
    )
    rendered_comment = _render_with_renderer(comment_payload)
    assert "onerror" not in rendered_comment
    pdf2, _, _ = print_backend.build_pdf(
        rendered_comment, width_mm=100, height_mm=150, unit="mm"
    )
    text2 = _pdf_text(pymupdf, pdf2)
    assert "MARKER-OK" in text2
    assert "SCRIPT-RAN" not in text2

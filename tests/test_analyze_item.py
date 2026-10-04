"""tools/analyze_item.py 的測試。模型 API 一律 fake，不發任何外部請求。

重點在兩件事：
  1. 邊界 —— 這個 adapter 沒有任何修改正式資料的管道（結構性，不是慣例）
  2. 嚴格 —— 模型輸出不合格式就直接報錯，不用 regex 猜測修復
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "analyze_item", ROOT / "tools" / "analyze_item.py"
)
analyzer = importlib.util.module_from_spec(SPEC)
sys.modules["analyze_item"] = analyzer
SPEC.loader.exec_module(analyzer)

SECRET = "sk-or-v1-THIS-MUST-NEVER-APPEAR-ANYWHERE"

PHOTOS = [
    {"id": "PHOTO1", "role": "original", "filename": "files/ITM-0001/original/a.jpg",
     "orig_name": "IMG_1.jpg"},
    {"id": "PHOTO2", "role": "original", "filename": "files/ITM-0001/original/b.jpg",
     "orig_name": "IMG_2.jpg"},
    {"id": "DERIVED1", "role": "derived", "filename": "files/ITM-0001/derived/t.webp",
     "orig_name": "t.webp"},
]

ITEM = {
    "id": "ITM-0001", "name": "", "brand": "", "model": "", "category": "",
    "quantity": 1, "condition": "", "notes": "", "status": "active",
}


class FakeItemTrace:
    """假的 ItemTrace：記錄所有呼叫，供斷言用。"""

    def __init__(self, photos=None, item=None):
        self.photos = PHOTOS if photos is None else photos
        self.item = dict(ITEM if item is None else item)
        self.calls: list[tuple[str, str]] = []
        self.suggestions: list[dict] = []

    def get_item(self, item_id):
        self.calls.append(("GET", f"/api/items/{item_id}"))
        return {"item": dict(self.item), "photos": self.photos,
                "observations": [], "identifiers": [], "suggestions": [],
                "suggestion_counts": {}}

    def list_suggestions(self, item_id):
        self.calls.append(("GET", f"/api/items/{item_id}/suggestions"))
        return list(self.suggestions)

    def get_photo_bytes(self, filename):
        self.calls.append(("GET", "/files/" + filename))
        return b"\xff\xd8\xff\xe0 fake jpeg bytes"

    def create_suggestion(self, item_id, payload):
        self.calls.append(("POST", f"/api/items/{item_id}/suggestions"))
        row = {"id": f"S{len(self.suggestions) + 1}", "status": "pending",
               "item_id": item_id, **payload}
        self.suggestions.append(row)
        return row


def model_json(suggestions):
    """假造一次成功的 OpenRouter 回應。"""
    return {
        "choices": [{"message": {"content": json.dumps({"suggestions": suggestions})}}]
    }


def fake_provider(payload):
    def provider(api_key, model, data_urls):
        provider.seen = {"api_key": api_key, "model": model, "data_urls": data_urls}
        return payload if isinstance(payload, dict) else model_json(payload)
    return provider


# ----------------------------------------------------------------------
# 1-2. 取得商品與照片
# ----------------------------------------------------------------------


def test_finds_original_photos_only():
    client = FakeItemTrace()
    analyzer.analyze(client, SECRET, "ITM-0001",
                     provider=fake_provider([]))
    fetched = [path for method, path in client.calls if method == "GET" and path.startswith("/files/")]
    assert fetched == ["/files/files/ITM-0001/original/a.jpg",
                       "/files/files/ITM-0001/original/b.jpg"]


def test_only_originals_are_sent():
    client = FakeItemTrace()
    analyzer.analyze(client, SECRET, "ITM-0001", provider=fake_provider([]))
    assert not any("t.webp" in path for _, path in client.calls)


def test_max_photos_is_respected():
    client = FakeItemTrace()
    analyzer.analyze(client, SECRET, "ITM-0001", max_photos=1,
                     provider=fake_provider([]))
    assert len([1 for m, p in client.calls if m == "GET" and p.startswith("/files/")]) == 1


def test_item_without_photos_is_an_error():
    client = FakeItemTrace(photos=[])
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(client, SECRET, "ITM-0001", provider=fake_provider([]))
    assert "沒有 original 照片" in str(excinfo.value)


def test_photo_url_is_a_base64_data_url():
    """區網照片不能把內網網址交給第三方，必須 base64。"""
    provider = fake_provider([])
    analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    for url in provider.seen["data_urls"]:
        assert url.startswith("data:image/")
        assert ";base64," in url
        base64.b64decode(url.split(";base64,", 1)[1])  # 確實是合法 base64


def test_request_body_order_is_text_then_images():
    """OpenRouter 官方建議文字在前、圖片在後。"""
    body = analyzer.build_request_body("m", ["data:image/jpeg;base64,AA", "data:image/jpeg;base64,BB"])
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert [c["type"] for c in content[1:]] == ["image_url", "image_url"]
    assert content[1]["image_url"]["url"].endswith("AA")


def test_request_body_pins_structured_output():
    body = analyzer.build_request_body("m", [])
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    fields = body["response_format"]["json_schema"]["schema"]["properties"][
        "suggestions"]["items"]["properties"]["field"]["enum"]
    assert set(fields) == set(analyzer.ALLOWED_FIELDS)


def test_request_body_does_not_pin_a_provider():
    """實測：免費變體只有一個 endpoint，provider 約束會讓請求直接 404。

    不加 provider 欄位，格式保護交給 parse_suggestions 的嚴格驗證。
    """
    body = analyzer.build_request_body("m", [])
    assert "provider" not in body


def test_allowed_fields_are_exactly_the_agreed_ones():
    assert set(analyzer.ALLOWED_FIELDS) == {
        "name", "brand", "model", "category", "condition",
        "identifier:serial", "identifier:imei", "identifier:barcode",
    }


# ----------------------------------------------------------------------
# 3-8. 模型輸出的驗證
# ----------------------------------------------------------------------


def test_valid_model_json_is_accepted():
    client = FakeItemTrace()
    created = analyzer.analyze(client, SECRET, "ITM-0001", provider=fake_provider([
        {"field": "brand", "value": "ASUS", "confidence": 0.92,
         "source_photo_index": 0},
    ]))
    assert len(created) == 1
    assert created[0]["status"] == "pending"


def test_invalid_json_is_an_error():
    provider = fake_provider({"choices": [{"message": {"content": "not json {"}}]})
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "不是合法 JSON" in str(excinfo.value)


def test_json_in_a_code_fence_is_not_silently_repaired():
    """不做 regex 猜測修復 —— 格式不對就報錯。"""
    fenced = '```json\n{"suggestions": []}\n```'
    provider = fake_provider({"choices": [{"message": {"content": fenced}}]})
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)


def test_missing_suggestions_key_is_an_error():
    provider = fake_provider({"choices": [{"message": {"content": "{}"}}]})
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "缺少 suggestions" in str(excinfo.value)


def test_suggestions_must_be_a_list():
    provider = fake_provider({"choices": [{"message": {"content": '{"suggestions": {}}'}}]})
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "必須是陣列" in str(excinfo.value)


def test_unknown_field_is_rejected():
    provider = fake_provider([{"field": "price", "value": "99", "confidence": 0.5,
                               "source_photo_index": 0}])
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "不在白名單" in str(excinfo.value)


@pytest.mark.parametrize("field", ["quantity", "status", "identifier:uuid", "notes"])
def test_non_whitelisted_fields_are_rejected(field):
    provider = fake_provider([{"field": field, "value": "x", "confidence": 0.5,
                               "source_photo_index": 0}])
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)


def test_empty_value_is_rejected():
    provider = fake_provider([{"field": "brand", "value": "   ", "confidence": 0.5,
                               "source_photo_index": 0}])
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "非空字串" in str(excinfo.value)


def test_confidence_below_zero_is_rejected():
    provider = fake_provider([{"field": "brand", "value": "ASUS", "confidence": -0.1,
                               "source_photo_index": 0}])
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "0~1" in str(excinfo.value)


def test_confidence_above_one_is_rejected():
    provider = fake_provider([{"field": "brand", "value": "ASUS", "confidence": 1.4,
                               "source_photo_index": 0}])
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "0~1" in str(excinfo.value)


def test_confidence_bounds_are_inclusive():
    for value in (0, 1, 0.0, 1.0):
        created = analyzer.analyze(
            FakeItemTrace(), SECRET, "ITM-0001",
            provider=fake_provider([{"field": "brand", "value": "ASUS",
                                     "confidence": value, "source_photo_index": 0}]),
        )
        assert created[0]["confidence"] == float(value)


def test_null_confidence_is_allowed():
    created = analyzer.analyze(
        FakeItemTrace(), SECRET, "ITM-0001",
        provider=fake_provider([{"field": "brand", "value": "ASUS",
                                 "confidence": None, "source_photo_index": 0}]),
    )
    assert created[0]["confidence"] is None


def test_confidence_of_wrong_type_is_rejected():
    provider = fake_provider([{"field": "brand", "value": "ASUS", "confidence": "高",
                               "source_photo_index": 0}])
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)


def test_out_of_range_photo_index_is_rejected():
    provider = fake_provider([{"field": "brand", "value": "ASUS", "confidence": 0.5,
                               "source_photo_index": 9}])
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "超出範圍" in str(excinfo.value)


def test_negative_photo_index_is_rejected():
    provider = fake_provider([{"field": "brand", "value": "ASUS", "confidence": 0.5,
                               "source_photo_index": -1}])
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)


def test_null_photo_index_is_allowed_and_maps_to_no_photo():
    created = analyzer.analyze(
        FakeItemTrace(), SECRET, "ITM-0001",
        provider=fake_provider([{"field": "category", "value": "主機板",
                                 "confidence": 0.6, "source_photo_index": None}]),
    )
    assert created[0]["source_photo_id"] is None


def test_non_object_suggestion_is_rejected():
    provider = fake_provider({"choices": [{"message": {"content": '{"suggestions": ["x"]}'}}]})
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "不是物件" in str(excinfo.value)


def test_empty_suggestions_creates_nothing():
    client = FakeItemTrace()
    created = analyzer.analyze(client, SECRET, "ITM-0001", provider=fake_provider([]))
    assert created == []
    assert not any(m == "POST" for m, _ in client.calls)


# ----------------------------------------------------------------------
# 9. suggestion payload
# ----------------------------------------------------------------------


def test_suggestion_payload_shape():
    client = FakeItemTrace()
    analyzer.analyze(client, SECRET, "ITM-0001", provider=fake_provider([
        {"field": "identifier:serial", "value": "BX-807 06_1234", "confidence": 0.77,
         "source_photo_index": 1},
    ]))
    posted = client.suggestions[0]
    assert posted["field"] == "identifier:serial"
    assert posted["value"] == "BX-807 06_1234"
    assert posted["confidence"] == 0.77
    assert posted["source"] == "external"
    assert posted["model_name"] == analyzer.DEFAULT_MODEL
    assert posted["actor"] == "external"


def test_source_photo_index_maps_to_the_real_photo_id():
    client = FakeItemTrace()
    analyzer.analyze(client, SECRET, "ITM-0001", provider=fake_provider([
        {"field": "brand", "value": "ASUS", "confidence": 0.9, "source_photo_index": 1},
    ]))
    assert client.suggestions[0]["source_photo_id"] == "PHOTO2"


def test_source_photo_id_is_a_real_itemtrace_photo():
    """source_photo_id 必須來自 ItemTrace 回的 photos，不能自己編。"""
    client = FakeItemTrace()
    analyzer.analyze(client, SECRET, "ITM-0001", provider=fake_provider([
        {"field": "brand", "value": "ASUS", "confidence": 0.9, "source_photo_index": 0},
    ]))
    known = {p["id"] for p in PHOTOS}
    assert client.suggestions[0]["source_photo_id"] in known


def test_model_name_is_the_actual_model_used():
    provider = fake_provider([{"field": "brand", "value": "ASUS", "confidence": 0.9,
                               "source_photo_index": 0}])
    client = FakeItemTrace()
    analyzer.analyze(client, SECRET, "ITM-0001", model="some/model:free",
                     provider=provider)
    assert provider.seen["model"] == "some/model:free"
    assert client.suggestions[0]["model_name"] == "some/model:free"


# ----------------------------------------------------------------------
# 10-11. 絕不 accept / reject
# ----------------------------------------------------------------------


def test_never_calls_accept_or_reject():
    client = FakeItemTrace()
    analyzer.analyze(client, SECRET, "ITM-0001", provider=fake_provider([
        {"field": "brand", "value": "ASUS", "confidence": 0.9, "source_photo_index": 0},
    ]))
    assert [path for _, path in client.calls if "accept" in path or "reject" in path] == []
    assert all(m == "GET" or (m == "POST" and path.endswith("/suggestions"))
               for m, path in client.calls)


def test_client_has_no_accept_or_reject_method():
    """邊界是結構性的：沒有方法就沒地方調。"""
    for forbidden in ("accept_suggestion", "reject_suggestion", "patch_item",
                      "update_item", "void_item", "delete_photo"):
        assert not hasattr(analyzer.ItemTraceClient, forbidden), forbidden


def test_client_route_allowlist_blocks_mutations():
    client = analyzer.ItemTraceClient("http://example.invalid")
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        client._request("POST", "/api/items/ITM-0001/void")
    assert "不得呼叫" in str(excinfo.value)
    with pytest.raises(analyzer.AnalyzerError):
        client._request("PATCH", "/api/items/ITM-0001")
    with pytest.raises(analyzer.AnalyzerError):
        client._request("POST", "/api/suggestions/S1/accept")


def test_client_allowlist_permits_exactly_the_three_operations():
    assert analyzer.ItemTraceClient.ALLOWED_ROUTES == (
        ("GET", r"^/api/items/[^/]+$"),
        ("GET", r"^/api/items/[^/]+/suggestions$"),
        ("GET", r"^/files/.+$"),
        ("POST", r"^/api/items/[^/]+/suggestions$"),
    )


def test_source_contains_no_accept_or_reject_calls():
    source = (ROOT / "tools" / "analyze_item.py").read_text(encoding="utf-8")
    assert "/accept" not in source
    assert "/reject" not in source
    assert '"PATCH"' not in source


def test_items_are_never_modified():
    """adapter 跑完之後 items 欄位必須一模一樣。"""
    client = FakeItemTrace()
    before = dict(client.item)
    analyzer.analyze(client, SECRET, "ITM-0001", provider=fake_provider([
        {"field": "brand", "value": "ASUS", "confidence": 0.9, "source_photo_index": 0},
    ]))
    assert client.item == before


# ----------------------------------------------------------------------
# 12-14. 失敗處理與祕密
# ----------------------------------------------------------------------


def test_provider_http_failure_is_reported():
    def failing(api_key, model, data_urls):
        raise analyzer.AnalyzerError("OpenRouter 回應 429")
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=failing)


def test_unexpected_provider_shape_is_reported():
    provider = fake_provider({"choices": []})
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert "回應格式不如預期" in str(excinfo.value)


def test_missing_api_key_message_is_clear(monkeypatch, capsys):
    """缺設定檔時要明確停下來，並說明怎麼建立。"""
    monkeypatch.setattr(analyzer, "load_config",
                        lambda *a, **k: (_ for _ in ()).throw(
                            analyzer.AnalyzerError(analyzer.MISSING_CONFIG)))
    code = analyzer.main(["ITM-0001"])
    captured = capsys.readouterr()
    assert code == 2
    assert "ai_config.local.json" in captured.err
    assert "ai_config.example.json" in captured.err


def test_api_key_is_never_printed(monkeypatch, capsys):
    config = analyzer.AiConfig(api_key=SECRET, model="m:free")
    monkeypatch.setattr(analyzer, "load_config", lambda *a, **k: config)

    def failing(client, api_key, item_id, *, model, max_photos, echo):
        raise analyzer.AnalyzerError(f"provider 回應包含 {api_key} 這段文字")

    monkeypatch.setattr(analyzer, "analyze", failing)

    assert analyzer.main(["ITM-0001"]) == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err
    assert "***" in captured.err


def test_redact_removes_the_key():
    assert SECRET not in analyzer.redact(f"錯誤訊息裡有 {SECRET}", SECRET)
    assert "sk-***" in analyzer.redact("token 是 sk-or-v1-abcdefghijk", None)


def test_redact_also_catches_keys_it_was_not_told_about():
    """就算不給 secret，也要擋掉看起來像 key 的字串。"""
    other = "sk-or-v1-somethingelse-entirely"
    assert other not in analyzer.redact(f"意外外洩：{other}", None)


def test_provider_error_path_redacts(capsys, monkeypatch):
    secret = analyzer.AiConfig(api_key=SECRET, model="m:free")

    def fake_urlopen(request, timeout=None):
        raise analyzer.urllib.error.HTTPError(
            "https://openrouter.ai", 401, "Unauthorized", {},
            __import__("io").BytesIO(f'{{"error":"bad key {SECRET}"}}'.encode()),
        )

    monkeypatch.setattr(analyzer.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(analyzer.AnalyzerError) as excinfo:
        analyzer.call_openrouter(secret.api_key, "m", [])
    assert SECRET not in str(excinfo.value)


def test_failing_provider_is_not_retried_with_another_model():
    """失敗就是失敗：不換模型、不重試、不動用付費模型。

    這比掃原始碼裡的字串強 —— 行為上就能看出來沒有「換一個模型試試」的邏輯。
    """
    attempted: list[str] = []

    def failing(api_key, model, data_urls):
        attempted.append(model)
        raise analyzer.AnalyzerError("OpenRouter 回應 429")

    with pytest.raises(analyzer.AnalyzerError):
        analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=failing)

    assert attempted == [analyzer.DEFAULT_MODEL], "只該嘗試預設模型一次"


def test_successful_run_uses_exactly_one_request_and_one_model():
    attempted: list[str] = []

    def provider(api_key, model, data_urls):
        attempted.append(model)
        return model_json([{"field": "brand", "value": "ASUS", "confidence": 0.9,
                            "source_photo_index": 0}])

    analyzer.analyze(FakeItemTrace(), SECRET, "ITM-0001", provider=provider)
    assert attempted == [analyzer.DEFAULT_MODEL]


def test_default_model_is_free():
    """預設模型必須是免費變體。付費模型只能由人明確用 --model 指定。"""
    assert analyzer.DEFAULT_MODEL.endswith(":free")
    assert analyzer.DEFAULT_MODEL == "qwen/qwen3.8-27b:free"


def test_default_model_is_free_and_vision():
    assert analyzer.DEFAULT_MODEL == "qwen/qwen3.8-27b:free"

"""`POST /api/items/{id}/ai/analyze`（手機「AI 自動填入」）的契約。

三件事：
  1. 推論與事實分離 —— 分析結果是 **pending suggestions**，
     這個端點自己不修改 items 主表；要有人 accept 才寫入
  2. 與外部 adapter 共用 shop/ai_client.py —— monkeypatch
     call_ai_provider 就能攔截所有外部呼叫，不發任何真實請求
  3. 任何回應都不含 API key（設定檔被導向暫存位置，
     測試絕不碰真的 tools/ai_config.local.json）
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from shop import ai_client, ai_config

SECRET = "sk-or-v1-TEST-LOCAL-KEY-0000000000"
MODEL = "seed/model:free"
PROVIDER = "openrouter"
BASE_URL = ai_config.DEFAULT_BASE_URL


def provider_response(suggestions: list[dict]) -> dict:
    """假造一次成功的 provider 回應（OpenAI Chat Completions 形狀）。"""
    return {
        "choices": [
            {"message": {"content": json.dumps({"suggestions": suggestions})}}
        ]
    }


def fake_jpeg(tag: int) -> bytes:
    """最小 JPEG 位元組（SOI … EOI）。不是真圖片也沒關係：
    encode_photo 遇到無法解析的檔案會原封不动送出去。"""
    return b"\xff\xd8\xff\xe0" + bytes((tag,)) + b"\x00" * 32 + b"\xff\xd9"


@pytest.fixture()
def ai_config_file(tmp_path, monkeypatch):
    """把 tools/ai_config.local.json 指到暫存位置。"""
    path = tmp_path / "ai_config.local.json"
    path.write_text(
        json.dumps({
            "api_key": SECRET, "model": MODEL,
            "provider": PROVIDER, "base_url": BASE_URL,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_config, "config_path", lambda *a, **k: path)
    return path


@pytest.fixture()
def fake_provider(monkeypatch):
    """取代 shop.ai_client.call_ai_provider，記錄請求並回假回應。"""
    calls: list[dict] = []

    def install(payload=None, raises=None):
        def fake(api_key, model, data_urls, *,
                 provider=None, base_url=None, timeout=None, context=""):
            calls.append({
                "api_key": api_key, "model": model,
                "data_urls": data_urls, "provider": provider,
                "base_url": base_url, "context": context,
            })
            if raises is not None:
                raise raises
            return payload

        monkeypatch.setattr(ai_client, "call_ai_provider", fake)
        return calls

    return install


def add_item_with_photos(repo, config, count=1, *, with_derived=False):
    """建立商品 + original 照片：metadata 寫進 DB，
    實際 image bytes 寫到 cfg.files_dir 對應路徑。"""
    item = repo.create_item()
    originals = []
    for index in range(count):
        name = f"IMG_{index}.jpg"
        data = fake_jpeg(index)
        filename = f"files/{item.id}/original/{name}"
        destination = config.files_dir / item.id / "original" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        originals.append(
            repo.add_photo(
                item.id, filename,
                orig_name=name,
                sha256=hashlib.sha256(data).hexdigest(),
                bytes=len(data),
                role="original",
            )
        )
    derived = []
    if with_derived:
        derived.append(
            repo.add_photo(
                item.id, f"files/{item.id}/derived/t.webp",
                orig_name="t.webp", role="derived",
            )
        )
    return item, originals, derived


# ----------------------------------------------------------------------
# A. 成功：201 + pending suggestions，主表不被修改
# ----------------------------------------------------------------------


def test_analyze_success_returns_pending_suggestions(
    repo, config, client, ai_config_file, fake_provider
):
    item, photos, _ = add_item_with_photos(repo, config, count=2)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
        {"field": "identifier:serial", "value": "BX-807 06_1234",
         "confidence": 0.77, "source_photo_index": 1},
    ]))

    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body, list) and len(body) == 2

    brand, serial = body
    for suggestion in body:
        assert suggestion["item_id"] == item.id
        assert suggestion["status"] == "pending"
        assert suggestion["source"] == "external"
        assert suggestion["model_name"] == MODEL
        assert suggestion["decided_at"] is None
    assert brand["field"] == "brand"
    assert brand["value"] == "ASUS"
    assert brand["confidence"] == 0.9
    assert brand["source_photo_id"] == photos[0].id
    assert serial["field"] == "identifier:serial"
    assert serial["value"] == "BX-807 06_1234"
    assert serial["source_photo_id"] == photos[1].id

    # 推論不寫主表
    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["brand"] == ""
    assert detail["item"]["model"] == ""
    assert detail["suggestion_counts"]["pending"] == 2

    # 建議真的寫進 DB（與回應一致）
    stored = client.get(f"/api/items/{item.id}/suggestions").json()
    assert [row["id"] for row in stored] == [row["id"] for row in body]

    # 事件語義：suggestion.created，actor 是 external
    events = client.get(f"/api/items/{item.id}/events").json()
    created = [e for e in events if e["type"] == "suggestion.created"]
    assert len(created) == 2
    assert all(e["actor"] == "external" for e in created)
    assert all(e["entity_type"] == "suggestion" for e in created)


def test_analyze_calls_the_shared_client_with_the_configured_settings(
    repo, config, client, ai_config_file, fake_provider
):
    """與外部 adapter 共用同一份 client：provider / base_url / model
    從 tools/ai_config.local.json 讀出來原樣傳下去。"""
    item, photos, _ = add_item_with_photos(repo, config, count=1)
    calls = fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))

    assert client.post(f"/api/items/{item.id}/ai/analyze").status_code == 201

    assert len(calls) == 1
    call = calls[0]
    assert call["api_key"] == SECRET
    assert call["model"] == MODEL
    assert call["provider"] == PROVIDER
    assert call["base_url"] == BASE_URL

    # 照片以 base64 data URL 送出（區網路徑不外洩），內容就是
    # 寫到 files/ 的那份 bytes
    data_urls = call["data_urls"]
    assert len(data_urls) == 1
    for url in data_urls:
        assert url.startswith("data:image/")
        assert ";base64," in url
        assert "http://" not in url and "https://" not in url
        payload = base64.b64decode(url.split(";base64,", 1)[1])
        assert payload.startswith(b"\xff\xd8")  # JPEG SOI


def test_analyze_sends_only_original_photos(
    repo, config, client, ai_config_file, fake_provider
):
    """衍生照片（縮圖）不是證據，不送 AI。"""
    item, originals, derived = add_item_with_photos(
        repo, config, count=1, with_derived=True
    )
    assert derived  # 確實有一張 derived
    calls = fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 201
    assert len(calls[0]["data_urls"]) == 1


def test_analyze_unknown_item_is_a_404(client, ai_config_file, fake_provider):
    calls = fake_provider(provider_response([]))
    response = client.post("/api/items/ITM-DOES-NOT-EXIST/ai/analyze")
    assert response.status_code == 404
    assert calls == []


# ----------------------------------------------------------------------
# B. 沒有照片
# ----------------------------------------------------------------------


def test_analyze_without_photos_is_a_400(
    repo, config, client, ai_config_file, fake_provider
):
    item = repo.create_item()
    calls = fake_provider(provider_response([]))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400
    assert "沒有 original 照片" in response.json()["detail"]
    assert calls == []
    assert client.get(f"/api/items/{item.id}/suggestions").json() == []


# ----------------------------------------------------------------------
# C. AI 尚未設定
# ----------------------------------------------------------------------


def test_analyze_without_ai_config_is_a_400_and_creates_nothing(
    repo, config, client, tmp_path, monkeypatch, fake_provider
):
    item, photos, _ = add_item_with_photos(repo, config)
    missing = tmp_path / "not-here" / "ai_config.local.json"
    monkeypatch.setattr(ai_config, "config_path", lambda *a, **k: missing)

    calls = fake_provider(provider_response([]))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400
    assert "找不到" in response.json()["detail"]
    assert calls == []
    assert client.get(f"/api/items/{item.id}/suggestions").json() == []


# ----------------------------------------------------------------------
# D. provider 失敗
# ----------------------------------------------------------------------


def test_analyze_provider_failure_is_a_400_without_leaking_the_key(
    repo, config, client, ai_config_file, fake_provider
):
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(
        raises=ai_client.AnalyzerError(
            f"AI 服務回應 401（model={MODEL}）：bad key {SECRET}"
        )
    )
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400
    assert "AI 服務回應 401" in response.json()["detail"]
    assert SECRET not in response.text
    assert client.get(f"/api/items/{item.id}/suggestions").json() == []


def test_analyze_bad_model_output_is_a_400(
    repo, config, client, ai_config_file, fake_provider
):
    """模型輸出不合格式 → 400，不會有半套資料變成 suggestion。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "price", "value": "99", "confidence": 0.5,
         "source_photo_index": 0},
    ]))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400
    assert "不在白名單" in response.json()["detail"]
    assert client.get(f"/api/items/{item.id}/suggestions").json() == []


# ----------------------------------------------------------------------
# provider unavailable 的端點回歸（2026-10-05 真實故障）
# ----------------------------------------------------------------------


def test_analyze_provider_unavailable_is_reported_as_provider_failure(
    repo, config, client, ai_config_file, fake_provider
):
    """報告中的 provider_unavailable 必須被當成 provider 故障回報。

    修之前這種 payload 會被說成「AI 服務回應格式不如預期」——
    把上游故障講成模型的問題。
    """
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(raises=ai_client.ProviderError(
        "AI 服務暫時無法使用（model=%s）：HTTP 502，provider_unavailable，"
        "JSON error injected into SSE stream" % MODEL
    ))

    response = client.post(f"/api/items/{item.id}/ai/analyze")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "暫時無法使用" in detail
    assert "provider_unavailable" in detail
    assert "回應格式不如預期" not in detail, "不可再把 provider 故障說成格式問題"


def test_analyze_provider_unavailable_creates_no_suggestion_and_no_event(
    repo, config, client, ai_config_file, fake_provider
):
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(raises=ai_client.ProviderError(
        f"AI 服務暫時無法使用（model={MODEL}）：HTTP 502，provider_unavailable"
    ))

    before = repo.get_item(item.id)
    response = client.post(f"/api/items/{item.id}/ai/analyze")

    assert response.status_code == 400
    assert client.get(f"/api/items/{item.id}/suggestions").json() == []
    after = repo.get_item(item.id)
    assert (after.name, after.brand, after.model, after.status) == (
        before.name, before.brand, before.model, before.status)
    assert repo.list_events(
        entity_type="item", entity_id=item.id
    ) == [e for e in repo.list_events(
        entity_type="item", entity_id=item.id
    ) if e.type == "item.created"]


def test_analyze_provider_failure_response_never_leaks_the_key(
    repo, config, client, ai_config_file, fake_provider
):
    item, photos, _ = add_item_with_photos(repo, config)
    gemini = "AIzaFakeGeminiKey0123456789ABCDEF"
    fake_provider(raises=ai_client.ProviderError(
        f"AI 服務暫時無法使用（model={MODEL}）：rejected {SECRET} / {gemini}"
    ))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400
    assert SECRET not in response.text
    assert gemini not in response.text
    assert "sk-***" in response.json()["detail"]


def test_analyze_still_treats_bad_model_output_as_a_model_problem(
    repo, config, client, ai_config_file, fake_provider
):
    """反向確認：模型輸出壞掉仍然走原本的格式錯誤路線。"""
    item, photos, _ = add_item_with_photos(repo, config)
    # call_ai_provider 回一個正常 envelope，但內容不是合法 JSON
    fake_provider({"choices": [{"message": {"content": "not-json"}}]})
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "不是合法 JSON" in detail
    assert "暫時無法使用" not in detail, "模型輸出問題不可說成 provider 故障"


def test_analyze_success_semantics_unchanged(
    repo, config, client, ai_config_file, fake_provider
):
    """成功路徑的既有 semantics 一個都不能變。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 201
    body = response.json()
    assert body[0]["status"] == "pending"
    assert body[0]["source"] == "external"
    assert body[0]["model_name"] == MODEL
    assert body[0]["field"] == "brand"
    assert body[0]["value"] == "ASUS"

    # actor 不是 Suggestion 的欄位，它是 suggestion.created 事件的 actor
    stored = repo.list_suggestions(item_id=item.id)
    assert [s.status for s in stored] == ["pending"]
    assert [s.source for s in stored] == ["external"]
    assert [s.model_name for s in stored] == [MODEL]

    events = repo.list_events(entity_type="suggestion", entity_id=stored[0].id)
    assert [e.type for e in events] == ["suggestion.created"]
    assert events[0].actor == "external"


# ----------------------------------------------------------------------
# E. accept：接受之後才修改主表
# ----------------------------------------------------------------------


def test_accept_writes_the_value_into_the_item_only_after_accept(
    repo, config, client, ai_config_file, fake_provider
):
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze").json()
    suggestion_id = body[0]["id"]

    # 分析完：主表沒動
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == ""

    accepted = client.post(f"/api/suggestions/{suggestion_id}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["decided_at"] is not None

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["brand"] == "ASUS"
    assert detail["suggestion_counts"]["accepted"] == 1
    assert detail["suggestion_counts"].get("pending", 0) == 0

    # 既有事件語義保留：created → accepted
    events = client.get(f"/api/items/{item.id}/events").json()
    types = [e["type"] for e in events]
    assert "suggestion.created" in types
    assert "suggestion.accepted" in types


def test_identifier_suggestion_accept_creates_an_identifier(
    repo, config, client, ai_config_file, fake_provider
):
    """identifier:serial 建議接受後另建 identifiers（帶來源照片與
    confidence），不改 items 主表欄位。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "identifier:serial", "value": "BX-807 06_1234",
         "confidence": 0.77, "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze").json()

    accepted = client.post(f"/api/suggestions/{body[0]['id']}/accept")
    assert accepted.status_code == 200

    identifiers = client.get(f"/api/items/{item.id}/identifiers").json()
    assert len(identifiers) == 1
    row = identifiers[0]
    assert row["kind"] == "serial"
    assert row["value"] == "BX-807 06_1234"
    assert row["source"] == "accepted_suggestion"
    assert row["source_photo_id"] == photos[0].id
    assert row["confidence"] == 0.77

    assert client.get(f"/api/items/{item.id}").json()["item"]["model"] == ""


# ----------------------------------------------------------------------
# F. 重新分析生命週期（Phase 2A）：supersede、失敗保留、重試不重複
# ----------------------------------------------------------------------


def test_reanalysis_supersedes_previous_pending_suggestions(
    repo, config, client, ai_config_file, fake_provider
):
    """成功的新一輪分析是最新詮釋：上一輪 pending 轉 superseded，
    新一輪才是 pending；主表始終不被 analyze 修改。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
        {"field": "model", "value": "B650E-F", "confidence": 0.8,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze").json()
    assert [s["status"] for s in first] == ["pending", "pending"]

    fake_provider(provider_response([
        {"field": "brand", "value": "acer", "confidence": 0.7,
         "source_photo_index": 0},
    ]))
    second = client.post(f"/api/items/{item.id}/ai/analyze").json()
    assert len(second) == 1

    rows = {
        row["id"]: row
        for row in client.get(f"/api/items/{item.id}/suggestions").json()
    }
    for old in first:
        assert rows[old["id"]]["status"] == "superseded"
        assert rows[old["id"]]["decided_at"] is not None
    assert rows[second[0]["id"]]["status"] == "pending"

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["suggestion_counts"]["pending"] == 1
    assert detail["item"]["brand"] == ""
    assert detail["item"]["model"] == ""

    # supersede 是可觀測的：事件與 actor 都留下來
    events = client.get(f"/api/items/{item.id}/events").json()
    superseded = [e for e in events if e["type"] == "suggestion.superseded"]
    assert len(superseded) == 2
    assert all(e["actor"] == "external" for e in superseded)


def test_reanalysis_leaves_decided_suggestions_as_history(
    repo, config, client, ai_config_file, fake_provider
):
    """已 accepted / rejected 的建議是歷史：重新分析不會讓它們復活，
    也不會把它們改成 pending。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
        {"field": "condition", "value": "有刮痕", "confidence": 0.5,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze").json()
    accepted = client.post(f"/api/suggestions/{first[0]['id']}/accept")
    rejected = client.post(f"/api/suggestions/{first[1]['id']}/reject")
    assert accepted.status_code == 200
    assert rejected.status_code == 200

    fake_provider(provider_response([
        {"field": "brand", "value": "acer", "confidence": 0.7,
         "source_photo_index": 0},
    ]))
    client.post(f"/api/items/{item.id}/ai/analyze")

    rows = {
        row["id"]: row
        for row in client.get(f"/api/items/{item.id}/suggestions").json()
    }
    assert rows[first[0]["id"]]["status"] == "accepted"
    assert rows[first[1]["id"]]["status"] == "rejected"
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == "ASUS"


def test_successful_empty_reanalysis_supersedes_stale_pending(
    repo, config, client, ai_config_file, fake_provider
):
    """成功但空的一輪也是最新詮釋（模型不確定就什麼都不說）：
    不讓舊 pending 無限期殘留 —— 它們已不在最新結果裡。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze").json()

    fake_provider(provider_response([]))
    second = client.post(f"/api/items/{item.id}/ai/analyze")
    assert second.status_code == 201
    assert second.json() == []

    rows = client.get(f"/api/items/{item.id}/suggestions").json()
    assert rows[0]["id"] == first[0]["id"]
    assert rows[0]["status"] == "superseded"
    assert client.get(f"/api/items/{item.id}").json()["suggestion_counts"].get(
        "pending", 0
    ) == 0
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == ""


def test_failed_reanalysis_preserves_existing_pending_suggestions(
    repo, config, client, ai_config_file, fake_provider
):
    """失敗的分析什麼都不算：既有有效 pending 原封不動，
    不得被 supersede、也不會產生新資料。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze").json()

    fake_provider(raises=ai_client.ProviderError(
        f"AI 服務暫時無法使用（model={MODEL}）：HTTP 502，provider_unavailable"
    ))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400

    rows = client.get(f"/api/items/{item.id}/suggestions").json()
    assert [row["id"] for row in rows] == [first[0]["id"]]
    assert rows[0]["status"] == "pending"
    assert rows[0]["decided_at"] is None

    events = client.get(f"/api/items/{item.id}/events").json()
    assert "suggestion.superseded" not in [e["type"] for e in events]


def test_invalid_model_output_preserves_existing_pending_suggestions(
    repo, config, client, ai_config_file, fake_provider
):
    """模型輸出不合格式（算失敗）也不能動到既有 pending。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze").json()

    fake_provider({"choices": [{"message": {"content": "not-json"}}]})
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400

    rows = client.get(f"/api/items/{item.id}/suggestions").json()
    assert rows[0]["id"] == first[0]["id"]
    assert rows[0]["status"] == "pending"


def test_superseded_suggestion_cannot_be_accepted(
    repo, config, client, ai_config_file, fake_provider
):
    """已 superseded 的舊建議不能復活：接受被拒、主表不變。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze").json()

    fake_provider(provider_response([
        {"field": "brand", "value": "acer", "confidence": 0.7,
         "source_photo_index": 0},
    ]))
    second = client.post(f"/api/items/{item.id}/ai/analyze").json()

    response = client.post(f"/api/suggestions/{first[0]['id']}/accept")
    assert response.status_code == 400
    assert "superseded" in response.json()["detail"]
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == ""

    # 最新一輪仍然是 pending，沒有被舊建議的操作影響
    rows = {
        row["id"]: row
        for row in client.get(f"/api/items/{item.id}/suggestions").json()
    }
    assert rows[second[0]["id"]]["status"] == "pending"


def test_accept_failure_reports_conflict_and_keeps_suggestion_pending(
    repo, config, client, ai_config_file, fake_provider
):
    """接受 identifier 建議時撞到同商品既有識別碼 → 409；
    建議維持 pending、不得被標成 accepted、不得建立重複識別碼。"""
    item, photos, _ = add_item_with_photos(repo, config)
    repo.add_identifier(item.id, "BX-807 06_1234", kind="serial")
    fake_provider(provider_response([
        {"field": "identifier:serial", "value": "BX-807 06_1234",
         "confidence": 0.77, "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze").json()

    response = client.post(f"/api/suggestions/{body[0]['id']}/accept")
    assert response.status_code == 409
    assert "已有相同" in response.json()["detail"]

    stored = client.get(f"/api/items/{item.id}/suggestions").json()[0]
    assert stored["status"] == "pending"
    assert stored["decided_at"] is None
    assert len(client.get(f"/api/items/{item.id}/identifiers").json()) == 1
    events = client.get(f"/api/items/{item.id}/events").json()
    suggestion_events = [
        e for e in events
        if e["entity_type"] == "suggestion" and e["entity_id"] == body[0]["id"]
    ]
    assert [e["type"] for e in suggestion_events] == ["suggestion.created"]


def test_retrying_accepted_suggestion_is_refused_without_duplicate_changes(
    repo, config, client, ai_config_file, fake_provider
):
    """重試已接受的建議 → 400；值不會被套用兩次、事件不重複。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze").json()
    suggestion_id = body[0]["id"]

    assert client.post(f"/api/suggestions/{suggestion_id}/accept").status_code == 200
    retry = client.post(f"/api/suggestions/{suggestion_id}/accept")
    assert retry.status_code == 400
    assert "accepted" in retry.json()["detail"]

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["brand"] == "ASUS"
    assert detail["suggestion_counts"]["accepted"] == 1

    events = client.get(f"/api/items/{item.id}/events").json()
    brand_changes = [
        e for e in events
        if e["type"] == "field.changed" and e["field"] == "brand"
    ]
    assert len(brand_changes) == 1
    accepted_events = [
        e for e in events
        if e["type"] == "suggestion.accepted" and e["entity_id"] == suggestion_id
    ]
    assert len(accepted_events) == 1


# ----------------------------------------------------------------------
# G. 證據累積與情境式重新理解（Phase 2B）
# ----------------------------------------------------------------------


def add_evidence_photo(client, item_id, filename="receipt.jpg", tag=99):
    """走與前端「加入照片」相同的路徑：新 observation → 上傳。"""
    observation = client.post(
        f"/api/items/{item_id}/observations", json={"kind": "recheck"}
    ).json()
    upload = client.post(
        f"/api/observations/{observation['id']}/photos",
        files=[("files", (filename, fake_jpeg(tag), "image/jpeg"))],
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert len(body["archived"]) == 1
    return body["archived"][0]


def test_analyze_sends_existing_context_and_new_evidence(
    repo, config, client, ai_config_file, fake_provider
):
    """重跑分析時：全部（或最新）證據 + 既有詮釋一起送給 AI。"""
    item, photos, _ = add_item_with_photos(repo, config, count=1)
    client.patch(f"/api/items/{item.id}", json={
        "name": "不明金屬零件",
        "attributes": {"purchase_date": "2026-05-10"},
    })
    receipt = add_evidence_photo(client, item.id)

    calls = fake_provider(provider_response([
        {"field": "name", "value": "牧田 18V 震動電鑽", "confidence": 0.9,
         "source_photo_index": 1},
        {"field": "attribute:vendor", "value": "光華商場", "confidence": 0.8,
         "source_photo_index": 1},
    ]))

    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 201
    call = calls[0]
    assert len(call["data_urls"]) == 2          # 舊照片 + 新證據
    assert "不明金屬零件" in call["context"]     # 既有詮釋進上下文
    assert "purchase_date" in call["context"]
    assert "2026-05-10" in call["context"]

    body = response.json()
    assert [s["field"] for s in body] == ["name", "attribute:vendor"]
    assert body[1]["source_photo_id"] == receipt["id"]

    # 分析仍不碰主表：使用者資料原封不動
    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["name"] == "不明金屬零件"
    assert detail["item"]["attributes"] == {"purchase_date": "2026-05-10"}


def test_analysis_keeps_oldest_and_newest_evidence_when_over_photo_limit(
    repo, config, client, ai_config_file, fake_provider
):
    """>8 張時取「最早 2＋最新 6」（Phase 2C-B）：兩端都不能丟。"""
    item, photos, _ = add_item_with_photos(repo, config, count=8)
    newest = add_evidence_photo(client, item.id, filename="receipt9.jpg", tag=77)

    calls = fake_provider(provider_response([
        {"field": "name", "value": "最早照片才有的標籤", "confidence": 0.9,
         "source_photo_index": 0},
        {"field": "model", "value": "最新證據才有的型號", "confidence": 0.9,
         "source_photo_index": 7},
    ]))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 201

    assert len(calls[0]["data_urls"]) == 8      # 上限就是 8
    by_field = {s["field"]: s for s in response.json()}
    assert by_field["name"]["source_photo_id"] == photos[0].id    # 最早進來了
    assert by_field["model"]["source_photo_id"] == newest["id"]   # 最新也在


def test_attribute_suggestions_are_strictly_validated(
    repo, config, client, ai_config_file, fake_provider
):
    """attribute:<key> 的 key 形狀由軟體強制：非法 key 整批失敗。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "attribute:Bad-Key", "value": "x", "confidence": 0.5,
         "source_photo_index": 0},
    ]))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "不在白名單" in detail
    assert "attribute:<key>" in detail
    assert client.get(f"/api/items/{item.id}/suggestions").json() == []


def test_analysis_rejects_too_many_suggestions(
    repo, config, client, ai_config_file, fake_provider
):
    """建議數量有上限，防止模型輸出塞爆 pending。"""
    from shop.ai_client import MAX_SUGGESTIONS

    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": f"B{index}", "confidence": 0.5,
         "source_photo_index": 0}
        for index in range(MAX_SUGGESTIONS + 1)
    ]))
    response = client.post(f"/api/items/{item.id}/ai/analyze")
    assert response.status_code == 400
    assert "超過上限" in response.json()["detail"]
    assert client.get(f"/api/items/{item.id}/suggestions").json() == []


def test_accepting_attribute_suggestion_merges_and_preserves_other_keys(
    repo, config, client, ai_config_file, fake_provider
):
    """接受屬性建議是單鍵合併：使用者自己填的 attributes 不會被清掉。"""
    item, photos, _ = add_item_with_photos(repo, config)
    client.patch(f"/api/items/{item.id}", json={"attributes": {"warranty": "兩年"}})
    fake_provider(provider_response([
        {"field": "attribute:vendor", "value": "光華商場", "confidence": 0.8,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze").json()

    accepted = client.post(f"/api/suggestions/{body[0]['id']}/accept")
    assert accepted.status_code == 200

    attributes = client.get(f"/api/items/{item.id}").json()["item"]["attributes"]
    assert attributes == {"warranty": "兩年", "vendor": "光華商場"}


def test_reinterpretation_updates_record_without_duplicate(
    repo, config, client, ai_config_file, fake_provider
):
    """收據情境（API 版）：同一筆紀錄被更新，id／建立時間／使用者備註不變。"""
    item, photos, _ = add_item_with_photos(repo, config)
    client.patch(f"/api/items/{item.id}", json={
        "name": "不明金屬零件", "notes": "看起來像電鑽",
    })
    before = client.get(f"/api/items/{item.id}").json()["item"]
    add_evidence_photo(client, item.id)

    fake_provider(provider_response([
        {"field": "name", "value": "牧田 18V 震動電鑽", "confidence": 0.95,
         "source_photo_index": 1},
        {"field": "attribute:vendor", "value": "光華商場", "confidence": 0.8,
         "source_photo_index": 1},
        {"field": "attribute:description", "value": "附購買收據的 18V 電鑽",
         "confidence": 0.75, "source_photo_index": 1},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze").json()
    assert [s["field"] for s in body] == [
        "name", "attribute:vendor", "attribute:description"]

    for suggestion in body:
        assert client.post(
            f"/api/suggestions/{suggestion['id']}/accept"
        ).status_code == 200

    after = client.get(f"/api/items/{item.id}").json()
    assert after["item"]["id"] == item.id == before["id"]
    assert after["item"]["created_at"] == before["created_at"]
    assert after["item"]["name"] == "牧田 18V 震動電鑽"
    assert after["item"]["notes"] == "看起來像電鑽"     # 使用者備註未被覆蓋
    assert after["item"]["attributes"]["vendor"] == "光華商場"
    assert after["item"]["attributes"]["description"] == "附購買收據的 18V 電鑽"
    assert len(after["photos"]) == 2                    # 原照片 + 收據
    assert len(client.get("/api/items").json()) == 1    # 沒有多出一筆紀錄


def test_failed_reinterpretation_keeps_photo_and_retry_is_clean(
    repo, config, client, ai_config_file, fake_provider
):
    """分析失敗：照片仍在、既有 pending 不失效；重試成功且不重複媒體。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze").json()

    add_evidence_photo(client, item.id)

    fake_provider(raises=ai_client.ProviderError(
        f"AI 服務暫時無法使用（model={MODEL}）：HTTP 502，provider_unavailable"
    ))
    failed = client.post(f"/api/items/{item.id}/ai/analyze")
    assert failed.status_code == 400

    detail = client.get(f"/api/items/{item.id}").json()
    assert len(detail["photos"]) == 2                   # 新證據還在
    pending = [s for s in detail["suggestions"] if s["status"] == "pending"]
    assert [s["id"] for s in pending] == [first[0]["id"]]

    # 重試：成功後依 Phase 2A 生命週期 supersede 舊 pending；媒體不重複
    fake_provider(provider_response([
        {"field": "name", "value": "牧田 18V 震動電鑽", "confidence": 0.9,
         "source_photo_index": 1},
    ]))
    retried = client.post(f"/api/items/{item.id}/ai/analyze")
    assert retried.status_code == 201

    detail = client.get(f"/api/items/{item.id}").json()
    by_id = {s["id"]: s for s in detail["suggestions"]}
    assert by_id[first[0]["id"]]["status"] == "superseded"
    assert len(detail["photos"]) == 2                   # 重試不重複照片
    assert detail["suggestion_counts"]["pending"] == len(retried.json())


# ----------------------------------------------------------------------
# H. Phase 2C-B：證據選擇＋可回復的自動套用＋衝突升級
# ----------------------------------------------------------------------


def _recorded_response_text(scenario_id: str) -> str:
    """讀 tools/eval_fixtures 錄下的真實模型輸出（純字串，不碰網路）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "eval_fixtures" / "recorded" / f"{scenario_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))["response_text"]


def test_photo_selection_boundaries():
    """≤8 全送；9 → [0,1,3..8]（最早 2＋最新 6）；12 → [0,1,6..11]。"""
    from shop.api import _select_photos_for_analysis

    assert _select_photos_for_analysis(list(range(8))) == list(range(8))
    assert _select_photos_for_analysis(list(range(9))) == [0, 1, 3, 4, 5, 6, 7, 8]
    assert _select_photos_for_analysis(list(range(12))) == [0, 1, 6, 7, 8, 9, 10, 11]


def test_auto_fill_empty_identity_and_notify(
    repo, config, client, ai_config_file, fake_provider
):
    """空的身分欄位自動填入；category 維持待確認；事件 actor=system。"""
    item, photos, _ = add_item_with_photos(repo, config)
    created_at = client.get(f"/api/items/{item.id}").json()["item"]["created_at"]

    fake_provider(provider_response([
        {"field": "brand", "value": "Makita", "confidence": 0.9,
         "source_photo_index": 0},
        {"field": "model", "value": "DHP484", "confidence": 0.9,
         "source_photo_index": 0},
        {"field": "category", "value": "工具", "confidence": 0.8,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    by_field = {s["field"]: s for s in body}

    assert by_field["brand"]["status"] == "accepted"
    assert by_field["brand"]["source"] == "auto"
    assert by_field["model"]["status"] == "accepted"
    assert by_field["category"]["status"] == "pending"      # T2：維持確認

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["brand"] == "Makita"
    assert detail["item"]["model"] == "DHP484"
    assert detail["item"]["id"] == item.id                  # 穩定 ID
    assert detail["item"]["created_at"] == created_at       # 建立時間不變

    events = client.get(f"/api/items/{item.id}/events").json()
    brand_changes = [e for e in events
                     if e["type"] == "field.changed" and e["field"] == "brand"]
    assert len(brand_changes) == 1
    assert brand_changes[0]["actor"] == "system"
    assert len([e for e in events if e["type"] == "suggestion.auto_applied"]) == 2


def test_auto_apply_rules_ignore_model_confidence(
    repo, config, client, ai_config_file, fake_provider
):
    """低信心但符合規則（空值＋有照片來源）→ 一樣自動；規則不看自報信心。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "Makita", "confidence": 0.05,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert body[0]["status"] == "accepted"
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == "Makita"


def test_auto_requires_photo_source(
    repo, config, client, ai_config_file, fake_provider
):
    """沒有來源照片 → 證據支持不足，不自動。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "Makita", "confidence": 0.9,
         "source_photo_index": None},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert body[0]["status"] == "pending"
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == ""


def test_user_typed_identity_is_never_auto_overwritten(
    repo, config, client, ai_config_file, fake_provider
):
    """使用者打過的名字：新證據只能進確認清單，不得自動覆蓋。"""
    item, photos, _ = add_item_with_photos(repo, config)
    client.patch(f"/api/items/{item.id}", json={"name": "不明金屬零件"})

    fake_provider(provider_response([
        {"field": "name", "value": "牧田 18V 震動電鑽", "confidence": 0.99,
         "source_photo_index": 0},
        {"field": "brand", "value": "牧田", "confidence": 0.95,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    by_field = {s["field"]: s for s in body}

    assert by_field["name"]["status"] == "pending"          # 使用者編輯 → 保護
    assert by_field["brand"]["status"] == "accepted"        # 空的 → 自動
    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["name"] == "不明金屬零件"
    assert detail["item"]["brand"] == "牧田"


def test_user_confirmed_identity_is_not_silently_revised(
    repo, config, client, ai_config_file, fake_provider
):
    """使用者確認過的（accept）值：新證據只能進確認清單。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze").json()   # 非 auto
    accepted = client.post(f"/api/suggestions/{first[0]['id']}/accept")
    assert accepted.status_code == 200
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == "ASUS"

    fake_provider(provider_response([
        {"field": "brand", "value": "acer", "confidence": 0.99,
         "source_photo_index": 0},
    ]))
    second = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert second[0]["status"] == "pending"
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == "ASUS"


def test_ai_derived_identity_can_be_auto_revised_and_old_term_searchable(
    repo, config, client, ai_config_file, fake_provider
):
    """系統自動填入的身分值可被新證據自動修訂；舊詞彙仍可搜尋。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "Makita", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert first[0]["status"] == "accepted"

    fake_provider(provider_response([
        {"field": "brand", "value": "牧田", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    second = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert second[0]["status"] == "accepted"

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["brand"] == "牧田"
    # 舊詞彙（曾自動套用 → accepted）仍找得到
    assert [i["id"] for i in client.get("/api/items?q=Makita").json()] == [item.id]
    assert [i["id"] for i in client.get("/api/items?q=牧田").json()] == [item.id]


def test_user_edited_attribute_is_never_auto_overwritten(
    repo, config, client, ai_config_file, fake_provider
):
    """使用者填過的屬性鍵：不得自動覆蓋（單鍵合併也要尊重來源）。"""
    item, photos, _ = add_item_with_photos(repo, config)
    client.patch(f"/api/items/{item.id}", json={"attributes": {"color": "紅色"}})

    fake_provider(provider_response([
        {"field": "attribute:color", "value": "藍色", "confidence": 0.99,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert body[0]["status"] == "pending"
    assert client.get(f"/api/items/{item.id}").json()["item"]["attributes"] == {
        "color": "紅色"
    }


def test_descriptive_attribute_auto_revision_keeps_old_searchable(
    repo, config, client, ai_config_file, fake_provider
):
    """描述性屬性：空值自動填入、auto 來源可修訂；舊描述仍可搜尋。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "attribute:description", "value": "灰色的金屬零件",
         "confidence": 0.8, "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert first[0]["status"] == "accepted"

    fake_provider(provider_response([
        {"field": "attribute:description", "value": "附購買收據的 18V 電鑽",
         "confidence": 0.85, "source_photo_index": 0},
    ]))
    second = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert second[0]["status"] == "accepted"

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["attributes"]["description"] == "附購買收據的 18V 電鑽"
    assert [i["id"] for i in client.get("/api/items?q=灰色的金屬零件").json()] == [
        item.id
    ]


def test_contradictory_evidence_is_escalated_not_merged(
    repo, config, client, ai_config_file, fake_provider
):
    """Phase 2C-A 的 L4 實測情境：標籤（TOSHIBA）與另一張收據（PChome）
    不得被靜默併成一筆 —— 身分可自動填入，但購買資訊必須進衝突確認。"""
    item, photos, _ = add_item_with_photos(repo, config, count=1)
    add_evidence_photo(client, item.id, filename="seagate_receipt.jpg", tag=42)

    fake_provider({"choices": [{"message": {
        "content": _recorded_response_text("L4_contradiction")}}]})
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    by_field = {s["field"]: s for s in body}

    # 身分（來自標籤照片）自動填入
    assert by_field["brand"]["status"] == "accepted"
    assert by_field["model"]["status"] == "accepted"
    # 識別碼與分類維持確認
    assert by_field["identifier:serial"]["status"] == "pending"
    assert by_field["category"]["status"] == "pending"
    # 購買資訊（來自另一張收據）升級為衝突，不得默默寫入
    for field in ("attribute:vendor", "attribute:amount",
                  "attribute:purchase_date"):
        assert by_field[field]["status"] == "pending"
        assert by_field[field]["source"] == "external_conflict"

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["brand"] == "TOSHIBA"
    assert detail["item"]["attributes"] == {}                # 沒有被併入
    assert len(detail["identifiers"]) == 0                   # 序號未自動建立


def test_receipt_on_same_photo_auto_fills_identity_and_purchase(
    repo, config, client, ai_config_file, fake_provider
):
    """Phase 2C-A 的 L3 實測情境：收據同時提供身分與購買資訊 → 可自動；
    使用者手打的品名與備註必須原封不動。"""
    item, photos, _ = add_item_with_photos(repo, config, count=1)
    client.patch(f"/api/items/{item.id}", json={
        "name": "不明金屬零件", "notes": "五金行買的，忘了名字",
    })
    add_evidence_photo(client, item.id, filename="makita_receipt.jpg", tag=43)

    fake_provider({"choices": [{"message": {
        "content": _recorded_response_text("L3_receipt_updates")}}]})
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    by_field = {s["field"]: s for s in body}

    assert by_field["brand"]["status"] == "accepted"
    assert by_field["model"]["status"] == "accepted"
    assert by_field["attribute:vendor"]["status"] == "accepted"
    assert by_field["attribute:amount"]["status"] == "accepted"
    assert by_field["attribute:purchase_date"]["status"] == "accepted"
    assert by_field["name"]["status"] == "pending"           # 使用者打的
    assert by_field["category"]["status"] == "pending"       # T2

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["name"] == "不明金屬零件"           # 未被覆蓋
    assert detail["item"]["notes"] == "五金行買的，忘了名字"   # 備註完好
    assert detail["item"]["brand"] == "牧田"
    assert detail["item"]["attributes"]["vendor"] == "光華商場"
    assert len(detail["photos"]) == 2


def test_duplicate_conflicting_values_escalate(
    repo, config, client, ai_config_file, fake_provider
):
    """同一輪對同一欄位給出兩種值 → 該欄位不得自動。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "TOSHIBA", "confidence": 0.99,
         "source_photo_index": 0},
        {"field": "brand", "value": "SEAGATE", "confidence": 0.98,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert [s["status"] for s in body] == ["pending", "pending"]
    assert all(s["source"] == "external_conflict" for s in body)
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == ""


def test_auto_skips_identical_values(
    repo, config, client, ai_config_file, fake_provider
):
    """與現值相同（或完全重複）的提案不占用建議；重試不產生重複列。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "Makita", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    client.post(f"/api/items/{item.id}/ai/analyze?auto=1")
    before = client.get(f"/api/items/{item.id}").json()["suggestion_counts"]

    fake_provider(provider_response([
        {"field": "brand", "value": "Makita", "confidence": 0.9,
         "source_photo_index": 0},
        {"field": "brand", "value": "Makita", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert body == []
    after = client.get(f"/api/items/{item.id}").json()["suggestion_counts"]
    assert after == before


def test_undo_restores_previous_value_and_locks_the_field(
    repo, config, client, ai_config_file, fake_provider
):
    """復原：值回到前值、建議變 rejected；之後同欄位不再自動。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "Makita", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    suggestion_id = body[0]["id"]
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == "Makita"

    undo = client.post(f"/api/suggestions/{suggestion_id}/undo")
    assert undo.status_code == 200
    assert undo.json()["status"] == "rejected"

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["brand"] == ""                     # 回到空值
    events = client.get(f"/api/items/{item.id}/events").json()
    restored = [e for e in events
                if e["type"] == "field.changed" and e["field"] == "brand"
                and e["actor"] == "user"]
    assert len(restored) == 1
    assert len([e for e in events if e["type"] == "suggestion.undone"]) == 1

    # 復原後 = 使用者表達了意圖 → 再分析不自動
    fake_provider(provider_response([
        {"field": "brand", "value": "acer", "confidence": 0.99,
         "source_photo_index": 0},
    ]))
    again = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert again[0]["status"] == "pending"
    assert client.get(f"/api/items/{item.id}").json()["item"]["brand"] == ""


def test_undo_attribute_removes_new_key_and_keeps_others(
    repo, config, client, ai_config_file, fake_provider
):
    """屬性復原：新鍵整個移除；其他屬性（含使用者填的）不受影響。"""
    item, photos, _ = add_item_with_photos(repo, config)
    client.patch(f"/api/items/{item.id}", json={"attributes": {"warranty": "兩年"}})

    fake_provider(provider_response([
        {"field": "attribute:origin", "value": "Made in Malaysia",
         "confidence": 0.9, "source_photo_index": 0},
    ]))
    body = client.post(f"/api/items/{item.id}/ai/analyze?auto=1").json()
    assert body[0]["status"] == "accepted"
    assert client.get(f"/api/items/{item.id}").json()["item"]["attributes"] == {
        "warranty": "兩年", "origin": "Made in Malaysia"
    }

    undo = client.post(f"/api/suggestions/{body[0]['id']}/undo")
    assert undo.status_code == 200
    assert client.get(f"/api/items/{item.id}").json()["item"]["attributes"] == {
        "warranty": "兩年"
    }


def test_undo_rejects_non_auto_suggestions(
    repo, config, client, ai_config_file, fake_provider
):
    """只有自動套用（source=auto、accepted）的建議可以復原。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    pending = client.post(f"/api/items/{item.id}/ai/analyze").json()
    assert client.post(f"/api/suggestions/{pending[0]['id']}/undo").status_code == 400

    client.post(f"/api/suggestions/{pending[0]['id']}/accept")
    assert client.post(f"/api/suggestions/{pending[0]['id']}/undo").status_code == 400


def test_failed_auto_analysis_changes_nothing(
    repo, config, client, ai_config_file, fake_provider
):
    """auto 模式失敗：不自動、不動既有 pending、不新增事件。"""
    item, photos, _ = add_item_with_photos(repo, config)
    fake_provider(provider_response([
        {"field": "brand", "value": "ASUS", "confidence": 0.9,
         "source_photo_index": 0},
    ]))
    first = client.post(f"/api/items/{item.id}/ai/analyze").json()

    before_events = len(client.get(f"/api/items/{item.id}/events").json())
    fake_provider(raises=ai_client.ProviderError(
        f"AI 服務暫時無法使用（model={MODEL}）：HTTP 503"
    ))
    failed = client.post(f"/api/items/{item.id}/ai/analyze?auto=1")
    assert failed.status_code == 400

    detail = client.get(f"/api/items/{item.id}").json()
    assert detail["item"]["brand"] == ""
    pending = [s for s in detail["suggestions"] if s["status"] == "pending"]
    assert [s["id"] for s in pending] == [first[0]["id"]]
    events = client.get(f"/api/items/{item.id}/events").json()
    assert len(events) == before_events
    assert not [e for e in events if e["type"] == "suggestion.auto_applied"]

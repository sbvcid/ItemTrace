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
                 provider=None, base_url=None, timeout=None):
            calls.append({
                "api_key": api_key, "model": model,
                "data_urls": data_urls, "provider": provider,
                "base_url": base_url,
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

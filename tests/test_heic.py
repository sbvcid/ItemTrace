"""HEIC／HEIF 完整匯入流程：解碼、預覽、AI 輸入與歸檔語意。

使用隔離資料目錄與暫存資料庫（conftest 的 config／client fixtures），
以 pillow-heif 產生小型有效 HEIC 測試影像。涵蓋：

- HEIC／HEIF 偵測、零解碼尺寸、JPEG 解碼（含方向校正）與 EXIF 時間。
- 上傳像素上限（50 MP）：metadata 造假與真實超限都在解碼前擋下。
- POST /api/inbox/preview：選取預覽只回 JPEG、不落盤、損毀檔明確失敗。
- intake 歸檔：原始 bytes／SHA-256／副檔名逐位元組不變；預覽與 AI 用
  JPEG，衍生預覽不會被登記成另一張原始證據照片。
- HEIF EXIF 拍攝時間來源正確；讀不到時沿用既有 fallback、不推測。
- 重複匯入（skipped）與取消（discard）在 HEIC 上行為一致。

pillow-heif 不存在時整個檔案跳過（HEIC 功能缺支援時其他格式不受影響，
由既有測試涵蓋）。
"""

from __future__ import annotations

import base64
import io
import json
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

pillow_heif = pytest.importorskip("pillow_heif")
pillow_heif.register_heif_opener()

from shop import ai_client, heif, limits, photos  # noqa: E402
from shop import inbox as inbox_mod  # noqa: E402
from shop.errors import ValidationError  # noqa: E402
from tests.conftest import make_jpeg, set_mtime  # noqa: E402

EXIF_STAMP = "2026:10:11 09:08:07"
EXIF_ISO = "2026-10-11T09:08:07"


def heic_bytes(
    *,
    width: int = 64,
    height: int = 48,
    color: tuple[int, int, int] = (180, 40, 40),
    exif_datetime: str | None = None,
    orientation: int | None = None,
    quality: int | None = None,
) -> bytes:
    """以 pillow-heif 產生一張小型有效 HEIC（可帶 EXIF DateTimeOriginal）。"""
    image = Image.new("RGB", (width, height), color)
    save_kwargs: dict = {"format": "HEIF"}
    if quality is not None:
        save_kwargs["quality"] = quality
    if exif_datetime is not None or orientation is not None:
        exif = Image.Exif()
        if exif_datetime is not None:
            exif[36867] = exif_datetime  # DateTimeOriginal
        if orientation is not None:
            exif[0x0112] = orientation
        save_kwargs["exif"] = exif.tobytes()
    buffer = io.BytesIO()
    image.save(buffer, **save_kwargs)
    return buffer.getvalue()


def write_heic(path: Path, **kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(heic_bytes(**kwargs))
    return path


@pytest.fixture(scope="module")
def oversize_heic() -> bytes:
    """真實編碼的 54 MP HEIC（超過 50 MP 上限）。

    刻意不用「改寫 metadata」的合成檔：pillow-heif 會套用 clap 清理
    矩形，純改 ispe 不一定反映到解碼尺寸；真實超限檔才能同時驗證
    「metadata 讀得到 → 解碼前擋下」的完整路徑。編碼一次、整個模組
    共用（模組層級 fixture）。
    """
    return heic_bytes(width=9000, height=6000, quality=1)


def decode_jpeg_size(payload: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(payload)) as image:
        return image.size


def upload_inbox(client, name: str, data: bytes, mime: str = "image/heic"):
    return client.post(
        "/api/inbox/photos",
        files=[("files", (name, data, mime))],
    )


def intake(client, relatives: list[str], **extra):
    return client.post(
        "/api/inbox/intake", json={"files": relatives, "kind": "intake", **extra}
    )


def install_ai(monkeypatch, suggestions=None, store=None, model="test/model:free"):
    """與 test_capture_ui 相同模式：patch AI 設定與 provider 呼叫。"""
    from shop import ai_config
    from shop.ai_config import AiConfig

    monkeypatch.setattr(
        ai_config, "load_config",
        lambda *a, **k: AiConfig(api_key="sk-test-0000000000", model=model),
    )

    def fake_provider(api_key, model, data_urls, *, provider=None, base_url=None,
                      timeout=None, context=""):
        if store is not None:
            store["data_urls"] = list(data_urls)
        return {
            "choices": [{
                "message": {"content": json.dumps(
                    {"suggestions": suggestions or []})},
            }],
        }

    monkeypatch.setattr(ai_client, "call_ai_provider", fake_provider)
    return store


# ----------------------------------------------------------------------
# 單元：偵測、尺寸、解碼、EXIF
# ----------------------------------------------------------------------


def test_is_heif_recognizes_heic_but_not_jpeg_or_avif():
    assert heif.is_heif(heic_bytes()) is True
    assert heif.is_heif(make_jpeg()) is False
    assert heif.is_heif(b"") is False
    assert heif.is_heif(b"not an image at all!") is False
    # AVIF 是瀏覽器可原生顯示的格式，不當 HEIC 處理。
    avif_ftyp = b"\x00\x00\x00\x20ftypavif\x00\x00\x00\x00avifmif1"
    assert heif.is_heif(avif_ftyp) is False


def test_heif_dimensions_zero_decode_from_metadata():
    data = heic_bytes(width=128, height=96)
    assert heif.heif_dimensions(data) == (128, 96)
    # 截斷到只剩開頭也讀不到 → 回 None（不猜）。
    assert heif.heif_dimensions(data[:20]) is None


def test_decode_to_jpeg_produces_browser_readable_jpeg():
    data = heic_bytes(width=2000, height=1500)
    jpeg = heif.decode_to_jpeg(data, max_side=1600, quality=80)
    assert jpeg is not None and jpeg.startswith(b"\xff\xd8\xff")
    width, height = decode_jpeg_size(jpeg)
    assert max(width, height) == 1600
    # 原始位元組不被修改（decode 是唯讀運算）。
    assert data == heic_bytes(width=2000, height=1500)


def test_decode_to_jpeg_applies_orientation_metadata():
    """orientation=6（旋轉 90 度）必須反映在預覽尺寸上。"""
    data = heic_bytes(width=64, height=48, orientation=6)
    jpeg = heif.decode_to_jpeg(data, max_side=1600, quality=80)
    assert jpeg is not None
    assert decode_jpeg_size(jpeg) == (48, 64)


def test_decode_to_jpeg_refuses_over_pixel_cap_before_expansion(oversize_heic):
    assert heif.heif_dimensions(oversize_heic) == (9000, 6000)
    assert heif.decode_to_jpeg(
        oversize_heic, max_side=1600, quality=80,
        max_pixels=limits.MAX_IMAGE_PIXELS,
    ) is None


def test_decode_to_jpeg_corrupted_returns_none():
    bad = b"\x00\x00\x00\x20ftypheic" + b"\x00" * 64
    assert heif.is_heif(bad) is True
    assert heif.decode_to_jpeg(bad, max_side=1600, quality=80) is None
    assert heif.heif_dimensions(bad) is None


def test_heif_exif_capture_time_extracted_and_missing_is_not_guessed():
    with_exif = heic_bytes(exif_datetime=EXIF_STAMP)
    assert photos.read_exif_captured_at(with_exif) == EXIF_ISO
    without_exif = heic_bytes()
    assert photos.read_exif_captured_at(without_exif) is None
    # 損毀內容不得被猜成任何時間。
    bad = b"\x00\x00\x00\x20ftypheic" + b"\x00" * 64
    assert photos.read_exif_captured_at(bad) is None


# ----------------------------------------------------------------------
# metadata：尺寸、EXIF 來源與 fallback
# ----------------------------------------------------------------------


def test_read_metadata_heic_dims_exif_and_sha(tmp_path):
    path = tmp_path / "IMG_0007.HEIC"
    path.write_bytes(heic_bytes(width=96, height=64, exif_datetime=EXIF_STAMP))
    metadata = photos.read_metadata(path)
    assert (metadata.width, metadata.height) == (96, 64)
    assert metadata.captured_at == EXIF_ISO
    assert metadata.captured_from == photos.EXIF_SOURCE
    assert metadata.sha256 == photos.sha256_of(path)
    assert metadata.bytes == path.stat().st_size


def test_read_metadata_heic_without_exif_falls_back_to_mtime(tmp_path):
    path = write_heic(tmp_path / "plain.heic")
    set_mtime(path, datetime(2026, 10, 2, 9, 8, 7))
    metadata = photos.read_metadata(path)
    assert metadata.captured_from == photos.MTIME_SOURCE
    assert metadata.captured_at == "2026-10-02T09:08:07"


def test_parse_metadata_heic_without_exif_uses_filename_stamp_only(tmp_path):
    data = heic_bytes()
    parsed = photos.parse_metadata(data, "20261011-120000_IMG.heic")
    assert parsed.captured_at == "2026-10-11T12:00:00"
    assert parsed.captured_from == photos.FILENAME_SOURCE

    parsed = photos.parse_metadata(data, "IMG_0001.HEIC")
    assert parsed.captured_at is None
    assert parsed.captured_from == photos.NO_SOURCE


# ----------------------------------------------------------------------
# 像素上限：零解碼擋下（上傳與預覽都要）
# ----------------------------------------------------------------------


def test_pixel_cap_rejects_oversize_heic_from_metadata_without_decode(oversize_heic):
    """54 MP 真實 HEIC：寬高由 metadata 零解碼讀出，解碼前即擋下。"""
    assert limits.image_dimensions(oversize_heic) == (9000, 6000)
    with pytest.raises(ValidationError) as excinfo:
        limits.check_image_pixels(oversize_heic, "IMG_54MP.HEIC")
    assert "像素過大" in str(excinfo.value)


def test_upload_over_50mp_heic_rejected_before_archive(client, config, oversize_heic):
    response = upload_inbox(client, "IMG_BIG.HEIC", oversize_heic)
    assert response.status_code == 400
    assert "像素過大" in response.json()["detail"]
    # 檔案不得落盤、不得建立任何紀錄。
    assert inbox_mod.scan_inbox(config) == []
    assert client.get("/api/items").json() == []


# ----------------------------------------------------------------------
# POST /api/inbox/preview（選取後的前端預覽）
# ----------------------------------------------------------------------


def test_inbox_preview_returns_jpeg_without_touching_disk(client, config):
    data = heic_bytes(width=320, height=240, exif_datetime=EXIF_STAMP)
    response = client.post(
        "/api/inbox/preview",
        files=[("file", ("IMG_0001.HEIC", data, "image/heic"))],
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/jpeg")
    assert decode_jpeg_size(response.content) == (320, 240)
    # 預覽不落盤、不進資料庫 —— inbox 與 items 都零變動。
    assert inbox_mod.scan_inbox(config) == []
    assert client.get("/api/items").json() == []
    # 原始位元組沒有被伺服器改寫（同一份輸入仍能解出相同尺寸）。
    assert heif.heif_dimensions(data) == (320, 240)


def test_inbox_preview_rejects_non_heic(client, config):
    response = client.post(
        "/api/inbox/preview",
        files=[("file", ("a.jpg", make_jpeg(), "image/jpeg"))],
    )
    assert response.status_code == 400
    assert "HEIC" in response.json()["detail"]


def test_inbox_preview_corrupted_heic_fails_honestly(client, config):
    bad = b"\x00\x00\x00\x20ftypheic" + b"\x00" * 64
    response = client.post(
        "/api/inbox/preview",
        files=[("file", ("broken.HEIC", bad, "image/heic"))],
    )
    assert response.status_code == 400
    assert "無法解碼" in response.json()["detail"]
    assert inbox_mod.scan_inbox(config) == []


def test_inbox_preview_over_50mp_rejected(client, oversize_heic):
    response = client.post(
        "/api/inbox/preview",
        files=[("file", ("IMG_BIG.HEIC", oversize_heic, "image/heic"))],
    )
    assert response.status_code == 400
    assert "像素過大" in response.json()["detail"]


# ----------------------------------------------------------------------
# intake 歸檔語意：原檔不變；預覽與 AI 用 JPEG
# ----------------------------------------------------------------------


def test_intake_keeps_original_bytes_sha_and_extension(client, config, repo):
    data = heic_bytes(width=96, height=64, exif_datetime=EXIF_STAMP)
    upload = upload_inbox(client, "IMG_0042.HEIC", data)
    assert upload.status_code == 201, upload.text
    staged = upload.json()["staged"]
    assert staged[0].endswith(".HEIC")

    # 落盤的 inbox 檔案與上傳位元組逐位元組相同。
    inbox_file = config.data_root / staged[0]
    assert inbox_file.read_bytes() == data

    done = intake(client, staged).json()
    assert len(done["archived"]) == 1
    photo = done["archived"][0]
    assert photo["role"] == "original"
    assert photo["orig_name"] == "IMG_0042.HEIC"
    assert photo["filename"].lower().endswith(".heic")
    assert photo["sha256"] == photos.sha256_bytes(data)
    assert (photo["width"], photo["height"]) == (96, 64)
    assert photo["captured_at"] == EXIF_ISO

    # 歸檔後的原檔仍是同一份位元組、同一個檔名（不是 JPEG 轉存）。
    archived_path = config.data_root / photo["filename"]
    assert archived_path.read_bytes() == data
    assert archived_path.suffix.lower() == ".heic"


def test_detail_preview_decodes_heic_and_keeps_evidence_single(client, config, repo):
    data = heic_bytes(width=640, height=480, exif_datetime=EXIF_STAMP)
    staged = upload_inbox(client, "IMG_0009.HEIC", data).json()["staged"]
    item_id = intake(client, staged).json()["item_id"]

    detail = client.get(f"/api/items/{item_id}").json()
    assert len(detail["photos"]) == 1
    photo = detail["photos"][0]

    first = client.get(f"/api/photos/{photo['id']}/preview")
    assert first.status_code == 200, first.text
    assert first.headers["content-type"].startswith("image/jpeg")
    assert decode_jpeg_size(first.content) == (640, 480)

    # 第二次走 derived/ 快取：仍是同一張 JPEG。
    second = client.get(f"/api/photos/{photo['id']}/preview")
    assert second.status_code == 200
    assert second.content == first.content
    derived = config.files_dir / item_id / "derived"
    cache_files = list(derived.glob("preview-v1-*.jpg"))
    assert len(cache_files) == 1

    # 衍生預覽不是 photos 資料列：證據仍只有一張 original。
    after = client.get(f"/api/items/{item_id}").json()
    assert len(after["photos"]) == 1
    assert after["photos"][0]["id"] == photo["id"]
    assert all(p["role"] == "original" for p in after["photos"])
    assert (config.data_root / photo["filename"]).read_bytes() == data


def test_photo_preview_serves_original_for_browser_formats(client, config):
    jpeg = make_jpeg(exif=EXIF_STAMP)
    staged = client.post(
        "/api/inbox/photos", files=[("files", ("a.jpg", jpeg, "image/jpeg"))]
    ).json()["staged"]
    item_id = intake(client, staged).json()["item_id"]
    photo = client.get(f"/api/items/{item_id}").json()["photos"][0]

    response = client.get(f"/api/photos/{photo['id']}/preview")
    assert response.status_code == 200
    assert response.content == jpeg  # 原檔直出，不重新編碼


def test_list_thumbnail_id_points_to_heic_photo(client, config):
    data = heic_bytes()
    staged = upload_inbox(client, "IMG_0010.HEIC", data).json()["staged"]
    item_id = intake(client, staged).json()["item_id"]
    photo = client.get(f"/api/items/{item_id}").json()["photos"][0]

    listing = client.get("/api/items").json()
    row = next(entry for entry in listing if entry["id"] == item_id)
    assert row["thumbnail"].lower().endswith(".heic")
    assert row["thumbnail_id"] == photo["id"]


# ----------------------------------------------------------------------
# AI 輸入：HEIC 在伺服器端解碼成 JPEG data URL
# ----------------------------------------------------------------------


def test_draft_analysis_sends_jpeg_for_heic(client, monkeypatch):
    seen = {}
    install_ai(monkeypatch, suggestions=[], store=seen)
    data = heic_bytes(width=2000, height=1500, exif_datetime=EXIF_STAMP)
    staged = upload_inbox(client, "IMG_0011.HEIC", data).json()["staged"]

    response = client.post("/api/inbox/analyze", json={"files": staged})
    assert response.status_code == 200, response.text
    assert len(seen["data_urls"]) == 1
    url = seen["data_urls"][0]
    assert url.startswith("data:image/jpeg;base64,")
    payload = base64.b64decode(url.split(",", 1)[1])
    assert payload.startswith(b"\xff\xd8\xff")
    # AI 看到的是縮圖（伺服器端解碼），不是 HEIC 原檔。
    assert max(decode_jpeg_size(payload)) == ai_client.MAX_SIDE


def test_item_analysis_sends_jpeg_for_archived_heic(client, monkeypatch):
    seen = {}
    install_ai(monkeypatch, suggestions=[
        {"field": "name", "value": "HEIC 測試", "confidence": 0.9,
         "source_photo_index": 0},
    ], store=seen)
    data = heic_bytes(exif_datetime=EXIF_STAMP)
    staged = upload_inbox(client, "IMG_0012.HEIC", data).json()["staged"]
    item_id = intake(client, staged).json()["item_id"]

    response = client.post(f"/api/items/{item_id}/ai/analyze")
    assert response.status_code == 201, response.text
    assert seen["data_urls"][0].startswith("data:image/jpeg;base64,")


# ----------------------------------------------------------------------
# 重複匯入與取消（與既有流程一致）
# ----------------------------------------------------------------------


def test_duplicate_heic_reimport_is_skipped_for_existing_item(client, config):
    """同一批內不同檔名的同樣位元組照既有語意處理（新紀錄不跨檔去重）；
    同一張 HEIC 再次匯入**既有紀錄** → skipped，不建立第二份證據。"""
    data = heic_bytes(exif_datetime=EXIF_STAMP)
    upload_inbox(client, "first.HEIC", data)
    upload_inbox(client, "second.HEIC", data)
    relative = sorted(entry.relative for entry in inbox_mod.scan_inbox(config))
    assert len(relative) == 2

    done = intake(client, relative[:1]).json()
    assert len(done["archived"]) == 1

    again = intake(client, relative[1:], item_id=done["item_id"]).json()
    assert again["archived"] == []
    assert len(again["skipped"]) == 1
    detail = client.get(f"/api/items/{done['item_id']}").json()
    assert len(detail["photos"]) == 1


def test_cancel_discard_heic_leaves_no_residue(client, config):
    """取消（capture 的 discard）：inbox 暫存清空、零正式紀錄、零殘檔。"""
    data = heic_bytes(exif_datetime=EXIF_STAMP)
    upload = upload_inbox(client, "cancel.HEIC", data)
    staged = upload.json()["staged"]

    discarded = client.post("/api/inbox/discard", json={"files": staged})
    assert discarded.status_code == 200
    assert discarded.json()["count"] == 1
    assert inbox_mod.scan_inbox(config) == []
    assert client.get("/api/items").json() == []
    assert client.get("/api/stats").json()["counts"]["photos"] == 0
    assert not (config.files_dir / "ITM-0001").exists()


def test_observation_upload_duplicate_heic_reported_as_skipped(client):
    """已存紀錄追加同一張 HEIC：skipped 回報既有照片，不建立第二份。"""
    data = heic_bytes(exif_datetime=EXIF_STAMP)
    staged = upload_inbox(client, "IMG_0013.HEIC", data).json()["staged"]
    item_id = intake(client, staged).json()["item_id"]

    observation = client.post(
        f"/api/items/{item_id}/observations", json={"kind": "recheck"}
    ).json()
    response = client.post(
        f"/api/observations/{observation['id']}/photos",
        files=[("files", ("again.HEIC", data, "image/heic"))],
    )
    assert response.status_code == 201
    result = response.json()
    assert result["archived"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["existing_photo_id"] is not None

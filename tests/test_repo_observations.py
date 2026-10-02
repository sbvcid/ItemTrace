"""observations 與 photos：多次觀測、照片不可破壞。"""

from __future__ import annotations

import pytest

from shop.errors import NotFoundError, ValidationError


@pytest.fixture()
def item(repo):
    return repo.create_item(name="主機板")


# ---------------------------------------------------------------- observations


def test_add_observation_uses_readable_id(repo, item):
    observation = repo.add_observation(item.id, kind="intake", note="出貨前拍攝")
    assert observation.id.startswith("OBS-")
    assert observation.id.endswith("-01")
    assert observation.kind == "intake"
    assert observation.item_id == item.id


def test_add_observation_ids_increment(repo, item):
    first = repo.add_observation(item.id)
    second = repo.add_observation(item.id, kind="recheck")
    assert second.id == first.id[:-2] + "02"
    assert second.kind == "recheck"


def test_add_observation_requires_existing_item(repo):
    with pytest.raises(NotFoundError):
        repo.add_observation("ITM-9999")


def test_observation_kind_is_restricted(repo, item):
    with pytest.raises(ValidationError) as excinfo:
        repo.add_observation(item.id, kind="return")
    assert "return" in str(excinfo.value)


def test_list_observations_orders_by_capture_time(repo, item):
    repo.add_observation(item.id, captured_at="2026-10-02T10:00:00")
    repo.add_observation(item.id, kind="recheck", captured_at="2026-10-05T09:00:00")
    assert [obs.captured_at for obs in repo.list_observations(item.id)] == [
        "2026-10-02T10:00:00",
        "2026-10-05T09:00:00",
    ]


def test_second_observation_does_not_touch_the_first(repo, item):
    """SPEC-v1 §4.2：補拍不影響原始觀測。"""
    first = repo.add_observation(item.id, captured_at="2026-10-02T10:00:00")
    repo.add_photo(item.id, f"files/{item.id}/original/a.jpg", observation_id=first.id)
    repo.add_observation(item.id, kind="recheck")
    assert len(repo.list_observations(item.id)) == 2
    assert len(repo.list_photos(observation_id=first.id)) == 1


def test_update_observation_writes_event(repo, item):
    observation = repo.add_observation(item.id, note="初稿")
    repo.update_observation(observation.id, {"note": "補拍細節"})
    history = repo.list_events("observation", observation.id)
    change = next(event for event in history if event.type == "field.changed")
    assert (change.field, change.prev_value, change.next_value) == ("note", "初稿", "補拍細節")


# --------------------------------------------------------------------- photos


def test_add_photo_defaults_to_original(repo, item):
    photo = repo.add_photo(item.id, f"files/{item.id}/original/20261002-143022_IMG_4821.jpg")
    assert photo.role == "original"
    assert photo.observation_id is None
    assert photo.bytes is None
    assert len(photo.id) == 26


def test_add_photo_keeps_original_filename(repo, item):
    photo = repo.add_photo(
        item.id,
        f"files/{item.id}/original/20261002-143022_IMG_4821.jpg",
        orig_name="IMG_4821.jpg",
        sha256="a" * 64,
        bytes=1234,
        width=4032,
        height=3024,
        captured_at="2026-10-02T14:30:22",
        angle="front",
    )
    assert photo.orig_name == "IMG_4821.jpg"
    assert photo.sha256 == "a" * 64
    assert photo.bytes == 1234


def test_photo_filename_must_be_relative(repo, item):
    """SPEC-v1 §3：整個資料夾要能搬移，所以庫內不能存絕對路徑。"""
    for bad in ("C:/Users/me/a.jpg", "/etc/a.jpg", "../../elsewhere/a.jpg",
                "files\\ITM-0001\\a.jpg", ""):
        with pytest.raises(ValidationError):
            repo.add_photo(item.id, bad)


def test_photo_filename_accepts_posix_relative(repo, item):
    photo = repo.add_photo(item.id, f"files/{item.id}/original/20261002-143022_IMG_4821.jpg")
    assert photo.filename.startswith("files/ITM-0001/")


def test_photo_role_is_restricted(repo, item):
    with pytest.raises(ValidationError):
        repo.add_photo(item.id, f"files/{item.id}/original/a.jpg", role="thumb")


def test_photo_cannot_belong_to_another_observation(repo, item):
    other = repo.create_item()
    observation = repo.add_observation(other.id)
    with pytest.raises(ValidationError) as excinfo:
        repo.add_photo(item.id, f"files/{item.id}/original/a.jpg", observation_id=observation.id)
    assert other.id in str(excinfo.value)


def test_photo_cannot_belong_to_missing_item(repo):
    with pytest.raises(NotFoundError):
        repo.add_photo("ITM-9999", "files/ITM-9999/original/a.jpg")


def test_list_photos_filters(repo, item):
    observation = repo.add_observation(item.id)
    repo.add_photo(item.id, f"files/{item.id}/original/a.jpg")
    repo.add_photo(item.id, f"files/{item.id}/original/b.jpg", observation_id=observation.id)
    repo.add_photo(item.id, f"files/{item.id}/derived/a.thumb.webp", role="derived")

    assert len(repo.list_photos(item_id=item.id)) == 3
    assert len(repo.list_photos(observation_id=observation.id)) == 1
    assert len(repo.list_photos(role="derived")) == 1
    assert len(repo.list_photos(role="original")) == 2


def test_original_photo_cannot_be_deleted(repo, item):
    """SPEC-v1 §1：原始資料不可破壞。"""
    photo = repo.add_photo(item.id, f"files/{item.id}/original/a.jpg")
    with pytest.raises(ValidationError) as excinfo:
        repo.delete_photo(photo.id)
    assert "derived" in str(excinfo.value)
    assert repo.get_photo(photo.id).id == photo.id


def test_derived_photo_can_be_deleted_with_snapshot(repo, item):
    photo = repo.add_photo(
        item.id, f"files/{item.id}/derived/a.thumb.webp", role="derived"
    )
    repo.delete_photo(photo.id)
    with pytest.raises(NotFoundError):
        repo.get_photo(photo.id)

    deleted = repo.list_events("photo", photo.id)[0]
    assert deleted.type == "photo.deleted"
    assert deleted.payload["filename"] == f"files/{item.id}/derived/a.thumb.webp"


def test_photo_role_change_then_delete(repo, item):
    photo = repo.add_photo(item.id, f"files/{item.id}/original/a.jpg")
    repo.update_photo(photo.id, {"role": "derived"})
    repo.delete_photo(photo.id)
    assert repo.list_photos(item_id=item.id) == []


def test_update_photo_writes_event(repo, item):
    photo = repo.add_photo(item.id, f"files/{item.id}/original/a.jpg", angle="")
    repo.update_photo(photo.id, {"angle": "label"})
    change = next(
        event for event in repo.list_events("photo", photo.id)
        if event.type == "field.changed"
    )
    assert (change.field, change.prev_value, change.next_value) == ("angle", "", "label")


def test_photo_cannot_be_moved_to_another_item(repo, item):
    other = repo.create_item()
    photo = repo.add_photo(item.id, f"files/{item.id}/original/a.jpg")
    with pytest.raises(ValidationError) as excinfo:
        repo.update_photo(photo.id, {"item_id": other.id})
    assert "item_id" in str(excinfo.value)

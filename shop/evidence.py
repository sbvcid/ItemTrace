"""單一 Item read-only evidence bundle export —— 不修改 DB、不建立新資料來源。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from shop import config as config_mod
from shop.errors import NotFoundError, ValidationError


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_filename(filename: str) -> str:
    p = PurePosixPath(filename)
    if p.is_absolute() or ".." in p.parts:
        raise ValidationError(f"bad photo path in export: {filename!r}")
    if "\\" in filename:
        raise ValidationError(f"bad sep in photo path: {filename!r}")
    return filename


def _serialize(obj) -> dict | list | str | int | float | bool | None:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    # dataclass / model instance with __dict__
    d = asdict(obj)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _write_json(dir_path: Path, name: str, data) -> Path:
    path = dir_path / name
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    return path


def build_bundle(
    item_id: str,
    repo,
    cfg: config_mod.Config,
) -> dict:
    """產生 bundle，回傳 manifest dict；實際檔案已寫入 bundle_dir。"""
    # Verify item exists (read-only; raises consistent 404)
    item = repo.get_item(item_id)

    # Collect evidence from existing repo methods (read-only)
    observations = repo.list_observations(item_id, limit=500)
    identifiers = repo.list_identifiers(item_id=item_id)
    events = repo.list_events("item", item_id, limit=500)
    photos = repo.list_photos(item_id=item_id, limit=500)

    # Bundle directory under data_root/evidence/<item_id>
    bundle_dir = cfg.data_root / "evidence" / item_id
    if bundle_dir.exists():
        import shutil
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Write JSON evidence
    item_path = _write_json(bundle_dir, "item.json", _serialize(item))
    observations_path = _write_json(
        bundle_dir, "observations.json", _serialize(observations)
    )
    identifiers_path = _write_json(
        bundle_dir, "identifiers.json", _serialize(identifiers)
    )
    events_path = _write_json(
        bundle_dir, "events.json", _serialize(events)
    )

    # Photos: byte-identical copy from files_dir, using basename inside bundle
    photo_dir = bundle_dir / "photos"
    photo_dir.mkdir(exist_ok=True)
    file_entries = []

    def _register(path: Path, rel_path: str) -> None:
        size = path.stat().st_size
        digest = _sha256_file(path)
        file_entries.append({
            "path": rel_path,
            "sha256": digest,
            "size": size,
        })

    # Register JSON files
    for p, rel in (
        (item_path, "item.json"),
        (observations_path, "observations.json"),
        (identifiers_path, "identifiers.json"),
        (events_path, "events.json"),
    ):
        _register(p, rel)

    # Photo files
    for photo in photos:
        safe_name = _safe_filename(photo.filename)
        src = cfg.data_root / safe_name
        if not src.is_file():
            raise NotFoundError(
                f"export photo missing for {item_id}: {photo.filename!r} (photo id {photo.id})"
            )
        dest_name = Path(safe_name).name
        dest = photo_dir / dest_name
        # Byte-identical copy; no re-encode/re-compress
        with src.open("rb") as fsrc:
            with dest.open("wb") as fdst:
                fdst.write(fsrc.read())
        _register(dest, f"photos/{dest_name}")

    # Manifest
    manifest = {
        "format": "itemtrace-evidence",
        "version": 1,
        "item_id": item.id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": file_entries,
    }
    # Manifest — include all exported files; self-reference uses baseline
    # digest of file before self-entry (standard verifiable convention).
    manifest_path = _write_json(bundle_dir, "manifest.json", manifest)
    digest_before_self = _sha256_file(manifest_path)
    size_before_self = manifest_path.stat().st_size
    manifest["files"].append({
        "path": "manifest.json",
        "sha256": digest_before_self,
        "size": size_before_self,
    })
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return {
        "bundle_dir": str(bundle_dir.resolve()),
        "item_id": item.id,
        "manifest_path": str(manifest_path.resolve()),
        "manifest": manifest,
    }

"""inbox 掃描與入庫落盤：檔案 → Observation → photos（SPEC-v1 §10 階段 3）。

資料流：

    inbox/ 的檔案
      → 讀 metadata（EXIF → mtime → 檔名，見 shop.photos）
      → 建立/沿用 Item 與一次 Observation
      → 搬進 files/<item-id>/original/YYYYMMDD-HHMMSS_<原檔名>
      → 寫 photos（filename 存相對 DATA_ROOT 的路徑）

三條不可妥協的規則：

* **原始照片不可被覆蓋** —— 目標檔名已存在就加流水號，永不覆寫；
  匯入失敗時把已搬走的檔案搬回原位。
* **資料庫只存相對路徑** —— 一律經過 config.relative()，讓整份資料夾可搬移。
* **original/ 與 derived/ 分離** —— 本模組只產生 original/。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import db, ids, photos
from .config import Config
from .errors import ConflictError, NotFoundError, ValidationError
from .models import Item, Observation, Photo
from .repo import Repository

ORIGINAL = "original"
DERIVED = "derived"

#: Windows 不允許的檔名字元，加上控制字元，一律換成底線。
_ILLEGAL = re.compile(r'[\x00-\x1f<>:"/\\|?*]')

#: 大部分檔案系統的單一檔名上限（ext4 / APFS / NTFS 都是 255 bytes）。
MAX_NAME_BYTES = 255


@dataclass(frozen=True, slots=True)
class InboxEntry:
    """inbox 裡的一個待處理檔案，還沒動過。"""

    path: Path
    relative: str
    captured_at: str | None
    captured_from: str
    bytes: int


@dataclass(frozen=True, slots=True)
class ArchivedPhoto:
    """已歸檔的照片。duplicate_of 指向同樣位元組的既有照片（撞號警示用）。"""

    photo: Photo
    duplicate_of: str | None


@dataclass(frozen=True, slots=True)
class IntakeResult:
    item: Item
    observation: Observation | None
    archived: list[ArchivedPhoto]
    skipped: list[InboxEntry]

    @property
    def duplicates(self) -> list[ArchivedPhoto]:
        return [entry for entry in self.archived if entry.duplicate_of is not None]


def original_dir(config: Config, item_id: str) -> Path:
    return ids.item_dir(config, item_id) / ORIGINAL


def derived_dir(config: Config, item_id: str) -> Path:
    return ids.item_dir(config, item_id) / DERIVED


def scan_inbox(config: Config, *, recursive: bool = True) -> list[InboxEntry]:
    """列出 inbox 待處理檔案，只讀不動。

    遞迴是因為手機上傳工具常常順手生出子資料夾；隱藏檔案（.DS_Store、
    .nomedia）略過，它們不是照片。
    """
    root = config.inbox_dir
    if not root.is_dir():
        return []

    candidates = sorted(root.rglob("*") if recursive else root.glob("*"))
    entries: list[InboxEntry] = []
    for path in candidates:
        if not path.is_file() or path.name.startswith("."):
            continue
        captured_at, captured_from = photos.read_captured_at(path)
        entries.append(
            InboxEntry(
                path=path,
                relative=config.relative(path),
                captured_at=captured_at,
                captured_from=captured_from,
                bytes=path.stat().st_size,
            )
        )
    return entries


def resolve_inbox_paths(config: Config, relatives: list[str]) -> list[Path]:
    """把 DATA_ROOT 相對路徑解析成安全的實體路徑，只接受 inbox/ 底下的。

    為什麼要自己擋：intake() 會把來源檔案搬到 items/ 的資料夾，所以要是
    有人送出 `files/ITM-0001/original/a.jpg`，那張已被歸檔的原始照片就會被
    搬到另一件商品底下 —— 等於毀掉既有證據。HTTP 介面只暴露 inbox/ 的檔名。

    解析後一律再確認仍在 inbox/ 內，擋掉 `inbox/../../etc/passwd` 這種。
    """
    inbox_root = config.inbox_dir.resolve()
    paths: list[Path] = []
    for raw in relatives:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError("檔名必須是非空字串")
        candidate = (config.data_root / raw).resolve()
        if not candidate.is_relative_to(inbox_root):
            raise ValidationError(f"只能處理 inbox/ 底下的檔案：{raw}")
        if not candidate.is_file():
            raise NotFoundError(f"inbox 裡沒有這個檔案：{raw}")
        paths.append(candidate)
    if not paths:
        raise ValidationError("沒有選任何檔案")
    return paths


def intake(
    config: Config,
    repo: Repository,
    sources: list[Path] | None = None,
    *,
    item_id: str | None = None,
    kind: str = "intake",
    note: str = "",
    angle: str = "",
    source: str = "manual",
    actor: str = "user",
) -> IntakeResult:
    """把照片收進資料庫與檔案庫。

    sources 為 None 代表處理整個 inbox。傳 item_id 是加到既有商品
    （SPEC-v1 §4.2 的重新觀測）；不傳就開新的 Item，欄位留空等建議被接受。

    全有全無：任何一個檔案出錯，已搬走的檔案全部搬回、資料庫交易撤銷，
    不留半套結果。
    """
    if sources is None:
        sources = [entry.path for entry in scan_inbox(config)]
    paths = _resolve_sources(config, sources)
    if not paths:
        raise ValidationError("沒有可入庫的檔案")

    pending = [_inspect(config, repo, path, item_id) for path in paths]
    usable = [entry for entry in pending if not entry.skip]
    if not usable:
        # 全部都是重複匯入：不開新商品、不開新觀測，只回報略過。
        item = repo.get_item(item_id) if item_id else None
        return IntakeResult(
            item=item,  # type: ignore[arg-type]
            observation=None,
            archived=[],
            skipped=[entry.entry for entry in pending],
        )

    item = repo.get_item(item_id) if item_id else None
    observation: Observation | None = None
    moved: list[tuple[Path, Path]] = []
    archived: list[ArchivedPhoto] = []
    try:
        # 整批包在一個交易裡：repo 的每個寫入自己開的交易會沿用外層，
        # 所以任何一步失敗，item / observation / photos 全部撤銷。
        with db.transaction(repo.conn):
            item = repo.get_item(item_id) if item_id else repo.create_item(actor=actor)
            observation = repo.add_observation(
                item.id,
                kind=kind,
                note=note,
                captured_at=_observation_time(usable),
                actor=actor,
            )
            for entry in usable:
                target = _target_for(config, item.id, entry.path.name, entry.metadata)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(entry.path), str(target))
                moved.append((entry.path, target))
                archived.append(
                    ArchivedPhoto(
                        photo=repo.add_photo(
                            item.id,
                            config.relative(target),
                            observation_id=observation.id,
                            role=ORIGINAL,
                            orig_name=entry.path.name,
                            sha256=entry.metadata.sha256,
                            bytes=entry.metadata.bytes,
                            width=entry.metadata.width,
                            height=entry.metadata.height,
                            captured_at=entry.metadata.captured_at,
                            angle=angle,
                            source=source,
                            actor=actor,
                        ),
                        duplicate_of=entry.duplicate_of,
                    )
                )
    except BaseException:
        for origin, target in reversed(moved):
            if target.exists():
                origin.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(origin))
        raise

    assert item is not None
    return IntakeResult(
        item=item,
        observation=observation,
        archived=archived,
        skipped=[entry.entry for entry in pending if entry.skip],
    )


@dataclass(frozen=True, slots=True)
class _Pending:
    path: Path
    entry: InboxEntry
    metadata: photos.PhotoMetadata
    duplicate_of: str | None
    skip: bool


def _resolve_sources(config: Config, sources: list[Path]) -> list[Path]:
    """去重、排序、確認每個檔案都在 DATA_ROOT 內。"""
    seen: dict[Path, Path] = {}
    for raw in sources:
        path = Path(raw)
        if not path.is_file():
            raise ValidationError(f"檔案不存在或不是檔案：{path}")
        config.relative(path)  # 在 DATA_ROOT 之外會直接拋 ConfigError
        seen[path.resolve()] = path
    return [seen[key] for key in sorted(seen)]


def _inspect(
    config: Config, repo: Repository, path: Path, item_id: str | None
) -> _Pending:
    """讀 metadata 並判斷重複。還沒有 item，所以這裡不決定落點。"""
    metadata = photos.read_metadata(path)
    entry = InboxEntry(
        path=path,
        relative=config.relative(path),
        captured_at=metadata.captured_at,
        captured_from=metadata.captured_from,
        bytes=metadata.bytes,
    )

    if item_id is not None:
        # 同一件商品已經有同樣位元組的原始照片 → 重複匯入，不產生第二份。
        duplicates = repo.find_photos_by_sha256(
            metadata.sha256, item_id=item_id, role=ORIGINAL
        )
        if duplicates:
            return _Pending(path, entry, metadata, duplicates[0].id, True)
        duplicate_of = None
    else:
        # 別的商品有同樣的位元組：照樣歸檔（不能搶別人的證據），
        # 但回報撞號讓人判斷是拍重複還是同一件。
        duplicates = repo.find_photos_by_sha256(metadata.sha256, role=ORIGINAL)
        duplicate_of = duplicates[0].id if duplicates else None

    return _Pending(path, entry, metadata, duplicate_of, False)


def _target_for(
    config: Config, item_id: str, filename: str, metadata: photos.PhotoMetadata
) -> Path:
    prefix = photos.timestamp_for_filename(metadata.captured_at) + "_"
    return unique_target(original_dir(config, item_id), safe_filename(filename, prefix))


def _observation_time(pending: list[_Pending]) -> str | None:
    """Observation 的時間取最早一張照片的拍攝時間，沒有就留空。"""
    times = [entry.metadata.captured_at for entry in pending if entry.metadata.captured_at]
    return min(times) if times else None


def unique_target(directory: Path, filename: str) -> Path:
    """在 directory 下找一個不會覆蓋任何東西的檔名。

    已存在就加 -2、-3…… 原始照片不可被處理流程覆蓋。
    """
    if not (directory / filename).exists():
        return directory / filename
    stem, dot, suffix = filename.rpartition(".")
    if not dot:
        stem, suffix = filename, ""
    for index in range(2, 10_000):
        target = directory / f"{stem}-{index}{'.' + suffix if suffix else ''}"
        if not target.exists():
            return target
    raise ConflictError(f"{directory} 底下取不到不重複的檔名了")


def save_to_inbox(config: Config, filename: str, data: bytes) -> Path:
    """把手機上傳的位元組落到 inbox/，永不覆蓋既有檔案。

    不寫 photos 資料庫記錄 —— inbox 是「待處理」，還不知道屬於哪件商品。
    """
    config.inbox_dir.mkdir(parents=True, exist_ok=True)
    target = unique_target(config.inbox_dir, sanitize_name(filename))
    target.write_bytes(data)
    return target


def archive_bytes(
    config: Config,
    repo: Repository,
    item_id: str,
    observation_id: str,
    filename: str,
    data: bytes,
    *,
    angle: str = "",
    source: str = "upload",
    actor: str = "user",
) -> Photo:
    """把上傳的位元組歸檔到既有 Observation（SPEC-v1 §5 的上傳端點）。

    與 intake 共用同一套命名與寫檔規則；差異只在出處是 HTTP 而非 inbox 檔案，
    所以沒有 mtime 可退。
    """
    with db.transaction(repo.conn):
        observation = repo.get_observation(observation_id)
        if observation.item_id != item_id:
            raise ValidationError(
                f"observation {observation_id} 屬於 {observation.item_id}，"
                f"不能掛在 {item_id} 上"
            )

        metadata = photos.parse_metadata(data, filename)
        duplicates = repo.find_photos_by_sha256(
            metadata.sha256, item_id=item_id, role=ORIGINAL
        )
        if duplicates:
            # 同一件商品不該有兩份同樣位元組的原始照片。
            # 呼叫端要嘛自己處理掉重複，要嘛明確允許 —— 見 API 層的回應。
            raise ConflictError(
                f"這張照片已經歸檔過了（{duplicates[0].id}，{duplicates[0].filename}）"
            )

        target = _target_for(config, item_id, filename, metadata)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        try:
            return repo.add_photo(
                item_id,
                config.relative(target),
                observation_id=observation_id,
                role=ORIGINAL,
                orig_name=filename,
                sha256=metadata.sha256,
                bytes=metadata.bytes,
                width=metadata.width,
                height=metadata.height,
                captured_at=metadata.captured_at,
                angle=angle,
                source=source,
                actor=actor,
            )
        except BaseException:
            # 資料庫寫不進去就別留下孤兒檔案
            target.unlink(missing_ok=True)
            raise


def sanitize_name(name: str) -> str:
    """把外部來不及的檔名整理成檔案系統能接受的形式（不加時間戳前綴）。"""
    cleaned = _ILLEGAL.sub("_", name).rstrip(" .")
    if not cleaned:
        cleaned = "photo"
    if len(cleaned.encode("utf-8")) > MAX_NAME_BYTES - 8:
        extension = _extension(cleaned)
        budget = MAX_NAME_BYTES - 8 - len(extension.encode("utf-8"))
        cleaned = _truncate_utf8(_stem(cleaned), max(budget, 0)) + extension
    return cleaned


def safe_filename(name: str, prefix: str) -> str:
    """組出 YYYYMMDD-HHMMSS_<原檔名>，並確保在檔案系統上合法且不過長。"""
    cleaned = sanitize_name(name)
    # 原檔名本來就以時間戳開頭時（多半是時間退路走到檔名那一階），
    # 再加一次前綴只會變成 20261002-143022_20261002-143022_…。
    if cleaned.startswith(prefix):
        return cleaned
    extension = _extension(cleaned)
    # Windows 會自動補副檔名，"a.jpg" 其實佔掉 8 + 4 個字元。
    if len((prefix + cleaned).encode("utf-8")) > MAX_NAME_BYTES - 8:
        budget = MAX_NAME_BYTES - 8 - len((prefix + extension).encode("utf-8"))
        cleaned = _truncate_utf8(_stem(cleaned), max(budget, 0)) + extension
    return prefix + cleaned


def _stem(name: str) -> str:
    stem, dot, _ = name.rpartition(".")
    return stem if dot else name


def _extension(name: str) -> str:
    _, dot, suffix = name.rpartition(".")
    return "." + suffix if dot and suffix else ""


def _truncate_utf8(text: str, budget: int) -> str:
    return text.encode("utf-8")[: max(budget, 0)].decode("utf-8", "ignore") or "photo"

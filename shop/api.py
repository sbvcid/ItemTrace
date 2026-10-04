"""FastAPI 應用：SPEC-v1 §5 的 HTTP 契約。

路由只做三件事：解析輸入、呼叫 Repository / shop.inbox、把結果轉成
shop.schemas 的模型。**不在路由裡寫 SQL** —— 所有查詢與寫入都在
Repository 裡，交易與 rollback 的行為因此與 CLI、測試完全一致。

例外對應（shop/errors.py）：

    NotFoundError   → 404
    ValidationError → 400
    ConflictError   → 409
    ConfigError     → 400

檔案只開放 `files/` 與 `inbox/` 兩個子樹：`files/` 是已歸檔的原始照片，
`inbox/` 是使用者剛上傳、還在建檔的待處理照片（Inbox 頁的預覽縮圖）。
DATA_ROOT 底下還有 catalog.db 與 config.json，不能一併端出去。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Iterator

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Query,
    Request,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config as config_mod, db as db_mod, ids
from . import inbox as inbox_mod
from . import photos as photos_mod
from .config import Config, ConfigError
from .errors import ConflictError, NotFoundError, ValidationError
from .repo import Repository
from .settings import router as settings_router
from .schemas import (
    EventOut,
    HealthOut,
    IdentifierCreate,
    IdentifierLookupOut,
    IdentifierOut,
    IdentifierPatch,
    InboxEntryOut,
    InboxGroupOut,
    InboxIntakeOut,
    InboxIntakeRequest,
    InboxListing,
    ItemCreate,
    ItemDetail,
    ItemListOut,
    ItemOut,
    ItemPatch,
    ObservationCreate,
    ObservationOut,
    ObservationPatch,
    PhotoOut,
    PhotoPatch,
    PhotoSkipped,
    PhotoUploadResult,
    SkippedFile,
    StatsOut,
    SuggestionCreate,
    SuggestionOut,
    to_out,
    to_outs,
)

router = APIRouter()

#: /api/inbox/group 用的預設時間間隔（分鐘）。SPEC 沒有定義門檻，
#: 見本模組 docstring 的說明 —— 做成參數是為了不把政策藏起來。
DEFAULT_GROUP_GAP_MINUTES = 30


def get_config(request: Request) -> Config:
    return request.app.state.config


def get_repo(request: Request) -> Iterator[Repository]:
    """每個請求一條連線；寫入方法自己開交易，巢狀沿用外層。"""
    with Repository.open(get_config(request)) as repo:
        yield repo


Repo = Annotated[Repository, Depends(get_repo)]


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or config_mod.load()
    app = FastAPI(
        title="商品證據與歸檔工具",
        version=__version__,
        description=(
            "local-first 商品證據與歸檔工具的 HTTP 介面。"
            "所有寫入都會留下 events，照片只存相對 DATA_ROOT 的路徑。"
        ),
    )
    app.state.config = cfg
    _register_error_handlers(app)
    app.include_router(router)
    app.include_router(settings_router)
    _register_ui(app)

    @app.get("/files/{path:path}", include_in_schema=False)
    def serve_file(path: str, cfg: Annotated[Config, Depends(get_config)]) -> FileResponse:
        return _serve_file(cfg, path)

    return app


UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def _register_ui(app: FastAPI) -> None:
    """掛上 Phase 6A／7 的頁面。

這些不是 API，所以不放進 OpenAPI（/docs 保持純 API 契約）。
頁面是靜態 HTML，資料全部由前端的 fetch 打 /api/*，後端不多做一層模板。

路由：/ 是 inbox（Phase 7）、/items 是列表、/items/{id} 是詳細頁、
/settings 是 AI 設定頁（Post-v1 / AI-2）。
"""
    if not UI_DIR.is_dir():  # 測試環境或未 checkout UI 時不影響 API
        return
    app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(UI_DIR / "inbox.html")

    @app.get("/items", include_in_schema=False)
    def items_page() -> FileResponse:
        return FileResponse(UI_DIR / "items.html")

    @app.get("/settings", include_in_schema=False)
    def settings_page() -> FileResponse:
        return FileResponse(UI_DIR / "settings.html")

    @app.get("/items/{item_id}", include_in_schema=False)
    def item_page(item_id: str) -> FileResponse:
        # item_id 不在這裡驗證：頁面殼子對任何 id 都一樣，
        # 真正的 404 由前端呼叫 /api/items/{id} 時得到。
        return FileResponse(UI_DIR / "item.html")


def _register_error_handlers(app: FastAPI) -> None:
    # pydantic 的請求驗證失敗預設回 422，但 SPEC 的「值不合法」一律是 400，
    # 混用兩個狀態碼會讓呼叫端分不清楚是哪一類問題。
    app.add_exception_handler(RequestValidationError, _handler(400))
    for exc_type, status in (
        (NotFoundError, 404),
        (ValidationError, 400),
        (ConflictError, 409),
        (ConfigError, 400),
    ):
        app.add_exception_handler(
            exc_type,
            _handler(status),  # type: ignore[arg-type]
        )


def _handler(status: int):
    async def handle(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": _detail(exc)})

    return handle


def _detail(exc: Exception) -> Any:
    if isinstance(exc, RequestValidationError):
        return [
            {"loc": list(error.get("loc", [])), "msg": error.get("msg", "")}
            for error in exc.errors()
        ]
    return str(exc)


# ----------------------------------------------------------------------
# Items
# ----------------------------------------------------------------------


@router.get("/api/items", response_model=list[ItemListOut], tags=["items"])
def list_items(
    repo: Repo,
    q: Annotated[str | None, Query(description="品名／品牌／型號／備註／識別碼")] = None,
    status: str | None = None,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ItemListOut]:
    items = repo.list_items(q=q, status=status, category=category,
                            limit=limit, offset=offset)
    summaries = repo.photo_summaries([item.id for item in items])
    return [
        ItemListOut(**base.model_dump(), **summaries[base.id])
        for base in to_outs(items)
    ]


@router.post("/api/items", response_model=ItemOut, status_code=201, tags=["items"])
def create_item(body: ItemCreate, repo: Repo) -> ItemOut:
    return to_out(
        repo.create_item(
            name=body.name,
            brand=body.brand,
            model=body.model,
            category=body.category,
            quantity=body.quantity,
            condition=body.condition,
            notes=body.notes,
            attributes=body.attributes,
            actor=body.actor,
        )
    )


@router.get("/api/items/{item_id}", response_model=ItemDetail, tags=["items"])
def get_item(item_id: str, repo: Repo) -> ItemDetail:
    item = repo.get_item(item_id)
    suggestions = repo.list_suggestions(item_id=item_id, limit=500)
    counts: dict[str, int] = {}
    for suggestion in suggestions:
        counts[suggestion.status] = counts.get(suggestion.status, 0) + 1
    return ItemDetail(
        item=to_out(item),
        observations=to_outs(repo.list_observations(item_id, limit=500)),
        photos=to_outs(repo.list_photos(item_id=item_id, limit=500)),
        identifiers=to_outs(repo.list_identifiers(item_id=item_id)),
        suggestions=to_outs(suggestions),
        suggestion_counts=counts,
    )


@router.patch("/api/items/{item_id}", response_model=ItemOut, tags=["items"])
def patch_item(item_id: str, body: ItemPatch, repo: Repo) -> ItemOut:
    return to_out(repo.update_item(item_id, body.changes(), actor=body.actor))


@router.post("/api/items/{item_id}/void", response_model=ItemOut, tags=["items"])
def void_item(item_id: str, repo: Repo) -> ItemOut:
    """軟刪除。資料與檔案都保留（SPEC-v1 §1）。"""
    return to_out(repo.void_item(item_id))


# ----------------------------------------------------------------------
# Observations & Photos
# ----------------------------------------------------------------------


@router.get(
    "/api/items/{item_id}/observations",
    response_model=list[ObservationOut],
    tags=["observations"],
)
def list_observations(item_id: str, repo: Repo) -> list[ObservationOut]:
    repo.get_item(item_id)
    return to_outs(repo.list_observations(item_id, limit=500))


@router.post(
    "/api/items/{item_id}/observations",
    response_model=ObservationOut,
    status_code=201,
    tags=["observations"],
)
def create_observation(
    item_id: str, body: ObservationCreate, repo: Repo
) -> ObservationOut:
    return to_out(
        repo.add_observation(
            item_id,
            kind=body.kind,
            note=body.note,
            captured_at=body.captured_at,
            actor=body.actor,
        )
    )


@router.patch(
    "/api/observations/{observation_id}",
    response_model=ObservationOut,
    tags=["observations"],
)
def patch_observation(
    observation_id: str, body: ObservationPatch, repo: Repo
) -> ObservationOut:
    return to_out(
        repo.update_observation(observation_id, body.changes(), actor=body.actor)
    )


@router.post(
    "/api/observations/{observation_id}/photos",
    response_model=PhotoUploadResult,
    status_code=201,
    tags=["photos"],
)
async def upload_photos(
    observation_id: str,
    repo: Repo,
    cfg: Annotated[Config, Depends(get_config)],
    files: Annotated[list[UploadFile], File(description="一或多張照片")] = None,
    angle: Annotated[str, Query()] = "",
) -> PhotoUploadResult:
    """上傳照片：存檔到 files/<item>/original/ 並寫 photos。

    重複（同一商品已有同樣 sha256）不回報失敗，而是列在 skipped 裡 ——
    手機一次傳八張，其中一張重複不該讓另外七張一起白傳。
    """
    if not files:
        raise ValidationError("沒有收到檔案（multipart 欄位名要是 files）")
    observation = repo.get_observation(observation_id)

    archived: list[PhotoOut] = []
    skipped: list[PhotoSkipped] = []
    for upload in files:
        data = await upload.read()
        name = upload.filename or "photo.jpg"
        try:
            photo = inbox_mod.archive_bytes(
                cfg, repo, observation.item_id, observation_id, name, data,
                angle=angle, source="upload",
            )
        except ConflictError as exc:
            existing = repo.find_photos_by_sha256(
                photos_mod.sha256_bytes(data),
                item_id=observation.item_id,
                role=inbox_mod.ORIGINAL,
            )
            skipped.append(
                PhotoSkipped(
                    orig_name=name,
                    reason=str(exc),
                    existing_photo_id=existing[0].id if existing else None,
                )
            )
            continue
        archived.append(to_out(photo))
    return PhotoUploadResult(archived=archived, skipped=skipped)


@router.patch("/api/photos/{photo_id}", response_model=PhotoOut, tags=["photos"])
def patch_photo(photo_id: str, body: PhotoPatch, repo: Repo) -> PhotoOut:
    return to_out(repo.update_photo(photo_id, body.changes(), actor=body.actor))


@router.delete("/api/photos/{photo_id}", status_code=204, tags=["photos"])
def delete_photo(photo_id: str, repo: Repo) -> None:
    """只刪 role='derived'；original 會被 repo 擋下（§1 原始資料不可破壞）。"""
    repo.delete_photo(photo_id)


# ----------------------------------------------------------------------
# Identifiers
# ----------------------------------------------------------------------


@router.get(
    "/api/items/{item_id}/identifiers",
    response_model=list[IdentifierOut],
    tags=["identifiers"],
)
def list_identifiers(item_id: str, repo: Repo) -> list[IdentifierOut]:
    repo.get_item(item_id)
    return to_outs(repo.list_identifiers(item_id=item_id))


@router.post(
    "/api/items/{item_id}/identifiers",
    response_model=IdentifierOut,
    status_code=201,
    tags=["identifiers"],
)
def create_identifier(
    item_id: str, body: IdentifierCreate, repo: Repo
) -> IdentifierOut:
    """撞號回 409 與既有 item 清單（§5）。確認是誤判後可用 allow_collision 放行。"""
    repo.get_item(item_id)
    conflicts = repo.find_identifier_conflicts(
        body.value, kind=body.kind, exclude_item_id=item_id
    )
    if conflicts and not body.allow_collision:
        existing = [
            {
                "identifier_id": row.id,
                "item_id": row.item_id,
                "kind": row.kind,
                "value": row.value,
                "normalized": row.normalized,
                "source": row.source,
            }
            for row in conflicts
        ]
        raise ConflictError(
            f"其他商品已有正規化後相同的識別碼：{existing}"
        )
    return to_out(
        repo.add_identifier(
            item_id,
            body.value,
            kind=body.kind,
            confidence=body.confidence,
            source=body.source,
            source_photo_id=body.source_photo_id,
            actor=body.actor,
        )
    )


@router.patch(
    "/api/identifiers/{identifier_id}",
    response_model=IdentifierOut,
    tags=["identifiers"],
)
def patch_identifier(
    identifier_id: str, body: IdentifierPatch, repo: Repo
) -> IdentifierOut:
    return to_out(
        repo.update_identifier(identifier_id, body.changes(), actor=body.actor)
    )


@router.delete("/api/identifiers/{identifier_id}", status_code=204, tags=["identifiers"])
def delete_identifier(identifier_id: str, repo: Repo) -> None:
    repo.delete_identifier(identifier_id)


@router.get(
    "/api/identifiers/lookup",
    response_model=IdentifierLookupOut,
    tags=["identifiers"],
)
def lookup_identifiers(
    repo: Repo,
    value: Annotated[str, Query(min_length=1, description="半截序號也可以")],
    kind: str | None = None,
) -> IdentifierLookupOut:
    """正規化後模糊比對（SPEC-v1 §7.1）。"""
    return IdentifierLookupOut(
        value=value,
        normalized=ids.normalize_identifier(value),
        matches=to_outs(repo.lookup_identifiers(value, kind=kind)),
    )


# ----------------------------------------------------------------------
# Suggestions
# ----------------------------------------------------------------------


@router.get(
    "/api/items/{item_id}/suggestions",
    response_model=list[SuggestionOut],
    tags=["suggestions"],
)
def list_suggestions(
    item_id: str, repo: Repo, status: str | None = None
) -> list[SuggestionOut]:
    repo.get_item(item_id)
    return to_outs(repo.list_suggestions(item_id=item_id, status=status, limit=500))


@router.post(
    "/api/items/{item_id}/suggestions",
    response_model=SuggestionOut,
    status_code=201,
    tags=["suggestions"],
)
def create_suggestion(
    item_id: str, body: SuggestionCreate, repo: Repo
) -> SuggestionOut:
    """外部工具寫入預測。主表不受影響，直到有人接受。"""
    return to_out(
        repo.add_suggestion(
            item_id,
            body.field,
            body.value,
            confidence=body.confidence,
            source=body.source,
            model_name=body.model_name,
            source_photo_id=body.source_photo_id,
            actor=body.actor,
        )
    )


@router.post(
    "/api/suggestions/{suggestion_id}/accept",
    response_model=SuggestionOut,
    tags=["suggestions"],
)
def accept_suggestion(suggestion_id: str, repo: Repo) -> SuggestionOut:
    """值寫入主表；identifier 類另建 identifiers。事件由 repo 產生。"""
    return to_out(repo.accept_suggestion(suggestion_id))


@router.post(
    "/api/suggestions/{suggestion_id}/reject",
    response_model=SuggestionOut,
    tags=["suggestions"],
)
def reject_suggestion(suggestion_id: str, repo: Repo) -> SuggestionOut:
    return to_out(repo.reject_suggestion(suggestion_id))


# ----------------------------------------------------------------------
# Events
# ----------------------------------------------------------------------


@router.get(
    "/api/items/{item_id}/events",
    response_model=list[EventOut],
    tags=["events"],
)
def item_events(
    item_id: str, repo: Repo, limit: Annotated[int, Query(ge=1, le=2000)] = 500
) -> list[EventOut]:
    return to_outs(repo.item_history(item_id, limit=limit))


@router.post(
    "/api/events/{event_id}/revert",
    response_model=ItemOut | ObservationOut | PhotoOut | IdentifierOut | SuggestionOut,
    tags=["events"],
)
def revert_event(event_id: str, repo: Repo) -> Any:
    """單欄位復原；復原本身也會再記一筆 field.changed。"""
    return to_out(repo.revert_event(event_id))


# ----------------------------------------------------------------------
# Inbox & System
# ----------------------------------------------------------------------


@router.get("/api/inbox", response_model=InboxListing, tags=["inbox"])
def list_inbox(
    cfg: Annotated[Config, Depends(get_config)],
    recursive: bool = True,
) -> InboxListing:
    entries = inbox_mod.scan_inbox(cfg, recursive=recursive)
    return InboxListing(
        entries=[
            InboxEntryOut(
                relative=entry.relative,
                captured_at=entry.captured_at,
                captured_from=entry.captured_from,
                bytes=entry.bytes,
            )
            for entry in entries
        ],
        count=len(entries),
    )


@router.post("/api/inbox/photos", response_model=InboxListing, status_code=201,
             tags=["inbox"])
async def upload_to_inbox(
    cfg: Annotated[Config, Depends(get_config)],
    files: Annotated[list[UploadFile], File()] = None,
) -> InboxListing:
    """手機上傳 → 落盤 inbox/。不寫資料庫，等按「處理」。"""
    if not files:
        raise ValidationError("沒有收到檔案（multipart 欄位名要是 files）")
    for upload in files:
        data = await upload.read()
        inbox_mod.save_to_inbox(cfg, upload.filename or "photo.jpg", data)
    entries = inbox_mod.scan_inbox(cfg)
    return InboxListing(
        entries=[
            InboxEntryOut(
                relative=entry.relative,
                captured_at=entry.captured_at,
                captured_from=entry.captured_from,
                bytes=entry.bytes,
            )
            for entry in entries
        ],
        count=len(entries),
    )


@router.post(
    "/api/inbox/intake",
    response_model=InboxIntakeOut,
    status_code=201,
    tags=["inbox"],
)
def start_intake(
    body: InboxIntakeRequest,
    repo: Repo,
    cfg: Annotated[Config, Depends(get_config)],
) -> InboxIntakeOut:
    """選定一組 → 建立 Item + Observation → 照片歸檔（SPEC-v1 §4.1 步驟 2-4）。

    這是 Phase 7 唯一新增的端點。`shop.inbox.intake()` 從階段 3 就已經能
    做這件事（搬檔 + 建檔 + 交易），缺的是一個能把「選好的檔名」餵進去的
    HTTP 介面 —— 既有端點都只吃新上傳的 multipart 位元組。

    全有全無：任一張失敗則整批撤銷，已搬走的檔案搬回 inbox。既有 original
    不會被覆寫（目標同名時加流水號）。
    """
    paths = inbox_mod.resolve_inbox_paths(cfg, body.files)
    result = inbox_mod.intake(
        cfg,
        repo,
        paths,
        item_id=body.item_id,
        kind=body.kind,
        note=body.note,
        actor=body.actor,
    )
    return InboxIntakeOut(
        item_id=result.item.id if result.item else None,
        observation_id=result.observation.id if result.observation else None,
        archived=[row.photo for row in result.archived],
        skipped=[SkippedFile(relative=row.relative) for row in result.skipped],
    )


@router.post("/api/inbox/group", response_model=list[InboxGroupOut], tags=["inbox"])
def group_inbox(
    cfg: Annotated[Config, Depends(get_config)],
    gap_minutes: Annotated[
        int,
        Query(ge=1, le=1440, description="相鄰兩張的時間差超過此值就切成新的一組"),
    ] = DEFAULT_GROUP_GAP_MINUTES,
) -> list[InboxGroupOut]:
    """依拍攝時間把 inbox 分組，產生待建檔批次（只預覽，不寫資料）。

    **SPEC 沒有定義分組門檻**，只有「依拍攝時間分組」一句（§4.1 步驟 2、
    §5 POST /api/inbox/group）。與其把政策藏成常數，不如做成參數並在
    /docs 標明預設值 30 分鐘，使用者可在 UI 端調整。
    """
    entries = sorted(
        (entry for entry in inbox_mod.scan_inbox(cfg) if entry.captured_at),
        key=lambda entry: entry.captured_at,
    )
    groups: list[InboxGroupOut] = []
    previous: Any = None
    for entry in entries:
        if previous is None or _minutes_between(previous, entry.captured_at) > gap_minutes:
            groups.append(
                InboxGroupOut(
                    index=len(groups),
                    captured_at=entry.captured_at,
                    captured_from=entry.captured_from,
                    entries=[],
                )
            )
        previous = entry.captured_at
        groups[-1].entries.append(
            InboxEntryOut(
                relative=entry.relative,
                captured_at=entry.captured_at,
                captured_from=entry.captured_from,
                bytes=entry.bytes,
            )
        )
    return groups


@router.get("/api/health", response_model=HealthOut, tags=["system"])
def health(cfg: Annotated[Config, Depends(get_config)]) -> HealthOut:
    return HealthOut(status="ok", schema_version=db_mod.version(cfg))


@router.get("/api/stats", response_model=StatsOut, tags=["system"])
def stats(repo: Repo, limit: Annotated[int, Query(ge=1, le=200)] = 10) -> StatsOut:
    return StatsOut(
        counts=repo.counts(),
        recent=to_outs(repo.list_recent_events(limit)),
        categories=repo.distinct_categories(),
    )


# ----------------------------------------------------------------------
# 靜態檔案
# ----------------------------------------------------------------------


def _serve_file(cfg: Config, path: str) -> FileResponse:
    """提供已歸檔照片與 inbox 待處理照片。

    photos.filename 與 InboxEntry.relative 存的都是相對 DATA_ROOT 的路徑
    （SPEC-v1 §3），所以網址要寫成 /files/files/ITM-0001/original/a.jpg、
    /files/inbox/a.jpg —— 前段 /files/ 是掛載點，後段才是資料庫存的相對路徑。

    只開放 files/ 與 inbox/ 兩個子樹：DATA_ROOT 底下還有 catalog.db 與
    config.json，解析後不在這兩個目錄內一律 404。
    """
    target = (cfg.data_root / path).resolve()
    roots = (cfg.files_dir.resolve(), cfg.inbox_dir.resolve())
    if not any(target.is_relative_to(root) for root in roots) or not target.is_file():
        raise NotFoundError(f"找不到檔案：{path}")
    return FileResponse(target)


def _minutes_between(earlier: str, later: str) -> float:
    return (
        datetime.fromisoformat(later) - datetime.fromisoformat(earlier)
    ).total_seconds() / 60

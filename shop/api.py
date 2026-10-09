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

import json
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

from . import __version__, ai_client, ai_config, config as config_mod, db as db_mod, ids
from . import inbox as inbox_mod
from . import photos as photos_mod
from . import print_backend as print_backend_mod
from . import template_renderer as template_renderer_mod
from .ai_config import AiConfigError
from .config import Config, ConfigError
from .errors import ConflictError, NotFoundError, ValidationError
from . import evidence as evidence_mod
from .models import Item, Photo
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
    PrinterOut,
    SkippedFile,
    StatsOut,
    SuggestionCreate,
    SuggestionOut,
    TemplateCreate,
    TemplateOut,
    TemplatePatch,
    TemplatePreviewRequest,
    TemplatePrintOut,
    TemplatePrintRequest,
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

    @app.get("/files/{path:path}", include_in_schema=False)
    def serve_file(path: str, cfg: Annotated[Config, Depends(get_config)]) -> FileResponse:
        return _serve_file(cfg, path)

    _register_web(app)
    _register_ui(app)

    return app


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def _register_web(app: FastAPI) -> None:
    """掛載 ItemTrace V3 現代零建置 Web 介面（web/ 目錄）。

    SPA 路由契約：
    1. 非 /api/* 與非 /files/* 的請求，若檔案存在則返回靜態檔案（如 .css, .js）。
    2. 其他前端路由（/capture, /i/:id, /settings 等）回退至 web/index.html 由客戶端 router 處理。
    3. 不干擾 /api/* 的 404 回應。
    """
    if not WEB_DIR.is_dir() or not (WEB_DIR / "index.html").is_file():
        return

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise NotFoundError(f"API 端點不存在：/{full_path}")
        if full_path:
            candidate = (WEB_DIR / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(WEB_DIR.resolve()):
                return FileResponse(candidate)
        return FileResponse(WEB_DIR / "index.html")


def _register_ui(app: FastAPI) -> None:
    """掛上 Phase 6A／7 的頁面。

    這些不是 API，所以不放進 OpenAPI（/docs 保持純 API 契約）。
    頁面是靜態 HTML，資料全部由前端的 fetch 打 /api/*，後端不多做一層模板。

    路由：/ 是 inbox（Phase 7）、/items 是列表、/items/{id} 是詳細頁、
    /settings 是 AI 設定頁（Post-v1 / AI-2）、/capture 是連續拍照、
    /settings/printing 是列印設定與範本管理頁。

    注意：Template 的上傳／預覽／CRUD 集中在 /settings/printing，
    商品頁只留「挑範本 → 預覽 → 列印」。
    """
    if not UI_DIR.is_dir() or not (UI_DIR / "inbox.html").is_file():  # 舊 UI 已移除或未 checkout 時不掛載舊頁面
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

    @app.get("/capture", include_in_schema=False)
    def capture_page() -> FileResponse:
        return FileResponse(UI_DIR / "capture.html")

    @app.get("/settings/printing", include_in_schema=False)
    def printing_settings_page() -> FileResponse:
        # 列印設定與範本管理。商品頁只留「挑範本 → 預覽 → 列印」，
        # Template 的 CRUD 集中在這裡。
        return FileResponse(UI_DIR / "printing_settings.html")

    @app.get("/items/{item_id}", include_in_schema=False)
    def item_page(item_id: str) -> FileResponse:
        # item_id 不在這裡驗證：頁面殼子對任何 id 都一樣，
        # 真正的 404 由前端呼叫 /api/items/{id} 時得到。
        return FileResponse(UI_DIR / "item.html")

    @app.get("/design", include_in_schema=False)
    def design_page() -> FileResponse:
        return FileResponse(UI_DIR / "design.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        # Minimal placeholder to avoid 404 console noise; no product feature.
        return FileResponse(UI_DIR / "favicon.ico")


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
    "/api/items/{item_id}/ai/analyze",
    response_model=list[SuggestionOut],
    status_code=201,
    tags=["suggestions"],
)
def analyze_item_photos(
    item_id: str,
    repo: Repo,
    cfg: Annotated[Config, Depends(get_config)],
    auto: Annotated[
        bool,
        Query(description="依政策自動套用低風險項目（可復原）；預設全部待確認"),
    ] = False,
) -> list[SuggestionOut]:
    """用商品的 original 照片跑 AI 分析（手機「AI 自動填入」按鈕）。

    結果是 **pending suggestions** —— 推論，不是事實。
    **預設（auto=false）**主表完全不受影響：要有人逐筆接受（POST
    /api/suggestions/{id}/accept）才會寫進商品（推論與事實分離，
    SPEC-v1 §1）。capture 的審閱流程與外部 adapter 都走這條。

    **auto=true（Phase 2C-B，詳情頁補證據後的重讀）**：依決定性的
    自主性政策（不看模型自報信心）把合格項目直接套用 ——
    描述性屬性、空的身分欄位、以及先前由系統自動填入的身分值；
    使用者編輯或確認過的欄位、識別碼、category/condition/notes
    一律留待確認；購買資訊只在「現值為空且同一張照片也提供身分
    資訊」時自動，否則升級為衝突確認。自動套用產生
    status='accepted'、source='auto' 的建議（可用
    POST /api/suggestions/{id}/undo 復原）。

    Phase 2B：照片會連同「目前的已知資訊」一起送出 —— 後補的證據
    （例如收據）能修正既有詮釋，而不是只看新照片從零猜。已知資訊
    只是上下文，prompt 明確要求以照片為準。

    AI 服務由 tools/ai_config.local.json 決定（provider /
    base_url / model / api_key），與外部 adapter
    tools/analyze_item.py 共用 shop/ai_client.py 同一份實作。
    """
    item = repo.get_item(item_id)  # 商品不存在 → 404
    photos = repo.list_photos(item_id=item_id, role="original", limit=500)
    if not photos:
        raise ValidationError(
            f"{item_id} 沒有 original 照片，沒有東西可以辨識。"
            " 先用 Inbox 建檔並上傳照片。"
        )
    photos = _select_photos_for_analysis(photos)

    try:
        ai = ai_config.load_config()
    except AiConfigError as exc:
        raise ValidationError(ai_config.redact(str(exc))) from None

    data_urls = []
    for photo in photos:
        data = _read_photo_bytes(cfg, photo.filename)
        data_urls.append(
            ai_client.photo_data_url(data, photo.orig_name or photo.filename)
        )

    try:
        response = ai_client.call_ai_provider(
            ai.api_key, ai.model, data_urls,
            provider=ai.provider, base_url=ai.base_url,
            context=_analysis_context(item),
        )
        text = ai_client.extract_text(response, ai.api_key)
        parsed = ai_client.parse_suggestions(
            text, [{"id": photo.id} for photo in photos]
        )
    except ai_client.AnalyzerError as exc:
        raise ValidationError(ai_config.redact(str(exc), ai.api_key)) from None

    # Phase 2A：成功的一輪是「最新詮釋」—— 舊 pending 在同一個交易內
    # 失效（superseded），失敗的分析（上面已 raise）永遠碰不到既有建議。
    # Phase 2C-B：auto=true 時同一交易內先套用政策合格的項目。
    applied, created, _superseded = repo.commit_analysis(
        item_id,
        parsed,
        model_name=ai.model,
        auto=auto,
        source="external",
        actor="external",
    )
    return to_outs([*applied, *created])


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


@router.post(
    "/api/suggestions/{suggestion_id}/undo",
    response_model=SuggestionOut,
    tags=["suggestions"],
)
def undo_suggestion(suggestion_id: str, repo: Repo) -> SuggestionOut:
    """復原一次「自動套用」（Phase 2C-B）：值回到前一個狀態。

    只允許 source='auto' 且 status='accepted' 的建議；復原本身記為
    使用者動作（寫回 actor=user），之後同一欄位不再被自動覆蓋。
    """
    return to_out(repo.undo_auto_suggestion(suggestion_id))


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


@router.get(
    "/api/items/{item_id}/evidence/export",
    tags=["evidence"],
)
def export_evidence(
    item_id: str,
    repo: Repo,
    cfg: Annotated[Config, Depends(get_config)],
) -> JSONResponse:
    """單一商品的 read-only evidence bundle export。"""
    result = evidence_mod.build_bundle(item_id, repo, cfg)
    return JSONResponse(content=result["manifest"])


@router.get(
    "/api/items/{item_id}/evidence/export/file",
    tags=["evidence"],
)
def export_evidence_file(
    item_id: str,
    path: Annotated[str, Query()],
    repo: Repo,
    cfg: Annotated[Config, Depends(get_config)],
) -> FileResponse:
    """讀取 bundle 中的單一檔案，路徑受控。"""
    # Verify item exists (same 404 semantics)
    repo.get_item(item_id)
    # Containment check: path relative to bundle_dir only
    bundle_dir = cfg.data_root / "evidence" / item_id
    target = (bundle_dir / path).resolve()
    if not target.is_relative_to(bundle_dir.resolve()) or not target.is_file():
        raise NotFoundError(f"bundle file not found: {path!r}")
    return FileResponse(target)


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


# ----------------------------------------------------------------------
# Templates (Phase 1)
# ----------------------------------------------------------------------


@router.get("/api/templates", response_model=list[TemplateOut], tags=["templates"])
def list_templates(
    repo: Repo,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TemplateOut]:
    return to_outs(repo.list_templates(limit=limit, offset=offset))


@router.post("/api/templates", response_model=TemplateOut, status_code=201, tags=["templates"])
def create_template(body: TemplateCreate, repo: Repo) -> TemplateOut:
    from .template_validator import validate_template
    validate_template(body.html)
    return to_out(
        repo.add_template(
            name=body.name,
            html=body.html,
            width=body.width,
            height=body.height,
            unit=body.unit,
            actor=body.actor,
        )
    )


@router.get("/api/templates/{template_id}", response_model=TemplateOut, tags=["templates"])
def get_template(template_id: str, repo: Repo) -> TemplateOut:
    return to_out(repo.get_template(template_id))


@router.put("/api/templates/{template_id}", response_model=TemplateOut, tags=["templates"])
def update_template(template_id: str, body: TemplatePatch, repo: Repo) -> TemplateOut:
    from .template_validator import validate_template
    if body.html is not None:
        validate_template(body.html)
    return to_out(
        repo.update_template(
            template_id,
            name=body.name,
            html=body.html,
            width=body.width,
            height=body.height,
            unit=body.unit,
            actor=body.actor,
        )
    )


@router.delete("/api/templates/{template_id}", status_code=204, tags=["templates"])
def delete_template(template_id: str, repo: Repo) -> None:
    repo.delete_template(template_id)


@router.post("/api/templates/{template_id}/preview", response_model=dict, tags=["templates"])
def preview_template(
    template_id: str,
    body: TemplatePreviewRequest,
    repo: Repo,
    cfg: Annotated[Config, Depends(get_config)],
) -> dict:
    """渲染 Template 預覽。

    回傳 rendered HTML 與使用的 Item 基本資訊。
    """
    template = repo.get_template(template_id)
    item = repo.get_item(body.item_id)
    rendered = template_renderer_mod.render_template_preview(template, item, repo, cfg)
    return {
        "html": rendered,
        "item_id": item.id,
        "item_name": item.name,
    }


def _rendered_html(template: Any, item: Any, repo: Repo, cfg: Config) -> str:
    """用**同一條 render pipeline** 渲染，預覽與列印共用。

    這是「預覽 = 實印」能成立的關鍵：這裡呼叫的是與 `/preview` 完全
    相同的 `render_template_preview`。print_backend 不做任何
    data-bind 處理，所以專案裡只有一套資料填充邏輯。
    """
    return template_renderer_mod.render_template_preview(
        template, item, repo, cfg
    )


def _print_html(template: Any, item: Any, repo: Repo, cfg: Config) -> str:
    """送進瀏覽器排版的**那份**列印 HTML（含 inline 照片）。

    `/preview` 回的是 `_rendered_html` 的原始輸出；這裡多一步
    `inline_photos`，把照片轉成 data URI。原因是排版發生在暫存檔
    (`file://`) 上，`/files/...` 在那裡解析不到，照片會整個消失。

    兩者的資料填充完全相同 —— 都只經過 `render_template_preview`，
    差別只有照片怎麼被載入。印表機對話框顯示的 html 與送進 PDF 的
    html 都是這個函式的產物，所以預覽與實印是同一份。
    """
    return print_backend_mod.inline_photos(
        _rendered_html(template, item, repo, cfg), _photo_reader(cfg)
    )


@router.get(
    "/api/printers", response_model=list[PrinterOut], tags=["templates"]
)
def list_printers() -> list[PrinterOut]:
    """列出可用的 Windows 印表機（給列印選單用）。"""
    names = print_backend_mod.list_printers()
    default = print_backend_mod.default_printer()
    return [PrinterOut(name=name, is_default=(name == default)) for name in names]


@router.post(
    "/api/templates/{template_id}/print-preview",
    response_model=TemplatePrintOut,
    tags=["templates"],
)
def print_preview_template(
    template_id: str,
    body: TemplatePreviewRequest,
    repo: Repo,
    cfg: Annotated[Config, Depends(get_config)],
) -> TemplatePrintOut:
    """產生列印輸出，但不送印表機。

    印表機對話框的「列印預覽」就是用這個回應的 `html` 渲染的 ——
    它與送進 PDF 的是同一份，所以看到的就是會印的。`width_mm` /
    `height_mm` 是實際的 PDF 頁面尺寸，UI 拿來顯示輸出尺寸。
    """
    template = repo.get_template(template_id)
    item = repo.get_item(body.item_id)
    print_html = _print_html(template, item, repo, cfg)
    _, width_mm, height_mm = print_backend_mod.build_pdf(
        print_html,
        width_mm=template.width,
        height_mm=template.height,
        unit=template.unit,
    )
    return TemplatePrintOut(
        printer="",
        item_id=item.id,
        item_name=item.name or "",
        template_id=template.id,
        width_mm=width_mm,
        height_mm=height_mm,
        pixel_width=0,
        pixel_height=0,
        dpi=print_backend_mod.DEFAULT_DPI,
        pdf_width_mm=width_mm,
        pdf_height_mm=height_mm,
        html=print_html,
    )


@router.post(
    "/api/templates/{template_id}/print",
    response_model=TemplatePrintOut,
    tags=["templates"],
)
def print_template(
    template_id: str,
    body: TemplatePrintRequest,
    repo: Repo,
    cfg: Annotated[Config, Depends(get_config)],
) -> TemplatePrintOut:
    """列印目前預覽（預設 1 份）。

    刻意不寫 events、也不動 Item：跟 `/preview` 一樣是唯讀操作，
    只是多了一個送到印表機的副作用。第一版不做列印歷史、不支援取消
    或排程 —— 那些都留給之後的需求。
    """
    template = repo.get_template(template_id)
    item = repo.get_item(body.item_id)
    result = print_backend_mod.print_html(
        _print_html(template, item, repo, cfg),
        template_id=template.id,
        item_id=item.id,
        width_mm=template.width,
        height_mm=template.height,
        unit=template.unit,
        printer=body.printer,
        photo_reader=_photo_reader(cfg),
    )
    return TemplatePrintOut(
        printer=result.printer,
        item_id=item.id,
        item_name=item.name or "",
        template_id=template.id,
        width_mm=result.width_mm,
        height_mm=result.height_mm,
        pixel_width=result.pixel_width,
        pixel_height=result.pixel_height,
        dpi=result.dpi,
        pdf_width_mm=result.pdf_width_mm,
        pdf_height_mm=result.pdf_height_mm,
        # 與送進 PDF 的是同一份，UI 可以據此確認「看到 = 會印」。
        html=_print_html(template, item, repo, cfg),
    )


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

    支援兩種路徑格式：
    1. 相對 files_dir：例如 ITM-0001/original/a.jpg（前端常見之 /files/ITM-0001/...）
    2. 相對 data_root：例如 files/ITM-0001/original/a.jpg 或 inbox/a.jpg（相容舊式 /files/files/... 或 /files/inbox/...）

    只開放 files/ 與 inbox/ 兩個子樹：DATA_ROOT 底下還有 catalog.db 與
    config.json，解析後不在這兩個目錄內一律 404。
    """
    roots = (cfg.files_dir.resolve(), cfg.inbox_dir.resolve())
    candidates = [
        (cfg.data_root / path).resolve(),
        (cfg.files_dir / path).resolve(),
        (cfg.inbox_dir / path).resolve(),
    ]
    for target in candidates:
        try:
            if any(target.is_relative_to(root) for root in roots) and target.is_file():
                return FileResponse(target, headers={"Cache-Control": "public, max-age=86400"})
        except (ValueError, OSError):
            continue

    raise NotFoundError(f"找不到檔案：{path}")


def _photo_reader(cfg: Config):
    """給 print_backend 的照片讀取 callable。

    沿用 `_read_photo_bytes` 的 containment 規則（只開放 files/ 子樹），
    找不到檔案回 None 而不是拋錯 —— 列印時照片缺失應該跟預覽一樣是
    空白，而不是讓整次列印失敗。
    """
    def read(relative: str) -> bytes | None:
        try:
            return _read_photo_bytes(cfg, relative)
        except NotFoundError:
            return None
    return read


def _read_photo_bytes(cfg: Config, filename: str) -> bytes:
    """讀已歸檔照片的原始 bytes（AI 分析用）。

    與 _serve_file 同一條 containment 規則：只開放 files/ 子樹，
    資料庫存的相對路徑不能逃出 DATA_ROOT/files。
    """
    target = (cfg.data_root / filename).resolve()
    if not target.is_relative_to(cfg.files_dir.resolve()) or not target.is_file():
        raise NotFoundError(f"找不到照片檔案：{filename}")
    return target.read_bytes()


def _analysis_context(item: Item) -> str:
    """把紀錄目前的已知資訊壓成給 AI 的上下文（Phase 2B）。

    這是「目前的詮釋」，不是事實 —— prompt 會要求以照片為準、
    仍正確的值可以原樣重提。notes 是使用者自己的備註，只作為
    理解輔助（prompt 明確說不需要重複建議）。
    """
    lines = []
    for label, value in (
        ("name", item.name),
        ("brand", item.brand),
        ("model", item.model),
        ("category", item.category),
        ("condition", item.condition),
        ("notes（使用者自己的備註）", item.notes),
    ):
        if value:
            lines.append(f"- {label}: {value}")
    if item.attributes:
        lines.append(
            "- attributes: "
            + json.dumps(item.attributes, ensure_ascii=False, sort_keys=True)
        )
    return "\n".join(lines)


def _select_photos_for_analysis(photos: list[Photo]) -> list[Photo]:
    """Phase 2C-B 證據選擇：≤8 全送；>8 取「最早 2＋最新 6」。

    評測（AI-EVALUATION-REPORT §4／L6）顯示：只取最新 8 張會把最早的
    intake 照片擠掉，而它通常是標籤／序號所在；最新的照片則是剛補的
    證據。兩端各留、中段冗餘先捨 —— 決定性、維持時間順序
    （source_photo_index 的語意不變）。
    """
    if len(photos) <= ai_client.MAX_PHOTOS:
        return photos
    return photos[:2] + photos[-(ai_client.MAX_PHOTOS - 2):]


def _minutes_between(earlier: str, later: str) -> float:
    return (
        datetime.fromisoformat(later) - datetime.fromisoformat(earlier)
    ).total_seconds() / 60

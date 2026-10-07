"""HTTP 請求／回應的形狀。

這些 pydantic 模型就是 SPEC-v1 §5 那份契約的實作，也是 /docs 與
OpenAPI 輸出的來源。欄位名沿用資料庫欄位名，避免多一層對照表。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from . import print_config
from .models import Event, Identifier, Item, Observation, Photo, Suggestion, Template


class _Out(BaseModel):
    """所有回應模型都從 sqlite 出來的 dataclass 直接轉出。"""

    model_config = ConfigDict(from_attributes=True)


class ItemOut(_Out):
    id: str
    name: str
    brand: str
    model: str
    category: str
    quantity: int
    condition: str
    notes: str
    attributes: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


class ItemListOut(ItemOut):
    """列表用：多帶照片數量與代表照片，讓 UI 不用為每筆各打一次詳情。

    這是加出來的欄位，不改 ItemOut，所以既有的詳情／PATCH 回應完全不受影響。
    """

    photo_count: int = 0
    thumbnail: str | None = None


class ItemCreate(BaseModel):
    name: str = ""
    brand: str = ""
    model: str = ""
    category: str = ""
    quantity: int = 1
    condition: str = ""
    notes: str = ""
    attributes: dict[str, Any] | None = None
    actor: str = "user"


class ItemPatch(BaseModel):
    """只給要改的欄位；沒給的不動（§5 的 PATCH 語意）。"""

    name: str | None = None
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    quantity: int | None = None
    condition: str | None = None
    notes: str | None = None
    attributes: dict[str, Any] | None = None
    status: str | None = None
    actor: str = "user"

    def changes(self) -> dict[str, Any]:
        supplied = self.model_dump(exclude_unset=True, exclude={"actor"})
        return {key: value for key, value in supplied.items() if value is not None}


class ObservationOut(_Out):
    id: str
    item_id: str
    kind: str
    note: str
    captured_at: str | None
    created_at: str


class ObservationCreate(BaseModel):
    kind: str = "intake"
    note: str = ""
    captured_at: str | None = None
    actor: str = "user"


class ObservationPatch(BaseModel):
    kind: str | None = None
    note: str | None = None
    captured_at: str | None = None
    actor: str = "user"

    def changes(self) -> dict[str, Any]:
        supplied = self.model_dump(exclude_unset=True, exclude={"actor"})
        return {key: value for key, value in supplied.items() if value is not None}


class PhotoOut(_Out):
    id: str
    item_id: str
    observation_id: str | None
    role: str
    filename: str
    orig_name: str
    sha256: str
    bytes: int | None
    width: int | None
    height: int | None
    captured_at: str | None
    angle: str
    source: str
    created_at: str


class PhotoPatch(BaseModel):
    """只能改 metadata 與角色，item_id 不在列表內（照片不跨商品移動）。"""

    observation_id: str | None = None
    role: str | None = None
    angle: str | None = None
    orig_name: str | None = None
    actor: str = "user"

    def changes(self) -> dict[str, Any]:
        supplied = self.model_dump(exclude_unset=True, exclude={"actor"})
        return {key: value for key, value in supplied.items() if value is not None}


class PhotoUploadResult(BaseModel):
    archived: list[PhotoOut] = Field(default_factory=list)
    skipped: list[PhotoSkipped] = Field(default_factory=list)


class PhotoSkipped(BaseModel):
    orig_name: str
    reason: str
    existing_photo_id: str | None = None


class IdentifierOut(_Out):
    id: str
    item_id: str
    kind: str
    value: str
    normalized: str
    confidence: float | None
    source: str
    source_photo_id: str | None
    created_at: str
    updated_at: str


class IdentifierCreate(BaseModel):
    value: str
    kind: str = "serial"
    confidence: float | None = None
    source: str = "human"
    source_photo_id: str | None = None
    #: §5 撞號回 409。確認是「同一件／打錯重打」後，用這個旗標明確放行，
    #: 讓 §2.3「撞號看得見、由人判斷」的目的仍然做得到。
    allow_collision: bool = False
    actor: str = "user"


class IdentifierPatch(BaseModel):
    value: str | None = None
    kind: str | None = None
    confidence: float | None = None
    source: str | None = None
    source_photo_id: str | None = None
    actor: str = "user"

    def changes(self) -> dict[str, Any]:
        supplied = self.model_dump(exclude_unset=True, exclude={"actor"})
        return {key: value for key, value in supplied.items() if value is not None}


class SuggestionOut(_Out):
    id: str
    item_id: str
    field: str
    value: str
    confidence: float | None
    source: str
    model_name: str
    source_photo_id: str | None
    status: str
    created_at: str
    decided_at: str | None


class SuggestionCreate(BaseModel):
    field: str
    value: str
    confidence: float | None = None
    source: str = "external"
    model_name: str = ""
    source_photo_id: str | None = None
    actor: str = "external"


class EventOut(_Out):
    id: str
    entity_type: str
    entity_id: str
    type: str
    actor: str
    field: str | None
    prev_value: Any
    next_value: Any
    payload: dict[str, Any]
    created_at: str


class TemplateOut(_Out):
    id: str
    name: str
    html: str
    width: float | None
    height: float | None
    unit: str | None
    created_at: str
    updated_at: str


class TemplateCreate(BaseModel):
    name: str
    html: str
    width: float | None = None
    height: float | None = None
    unit: str | None = None
    actor: str = "user"


class TemplatePatch(BaseModel):
    name: str | None = None
    html: str | None = None
    width: float | None = None
    height: float | None = None
    unit: str | None = None
    actor: str = "user"

    def changes(self) -> dict[str, Any]:
        supplied = self.model_dump(exclude_unset=True, exclude={"actor"})
        return {key: value for key, value in supplied.items() if value is not None}


class TemplatePreviewRequest(BaseModel):
    item_id: str
    actor: str = "user"


class TemplatePrintRequest(BaseModel):
    """列印目前預覽。

    第一版固定 1 份、不支援選擇數量：需求只要求「預設列印目前預覽 1 份」。
    `printer` 留給多印表機環境；None 代表用 Windows 預設印表機。
    """

    item_id: str
    printer: str | None = None


class TemplatePrintOut(BaseModel):
    """列印結果。

    回報實際送進印表機的物理尺寸（mm）而不只是請求值 —— 測試與使用者
    都能確認尺寸真的沒被縮放。

    `html` 是**實際拿去產生 PDF 的那一份 HTML**（`/print-preview` 才會填）。
    印表機對話框直接顯示它，所以「看到的」就是「會印的」：UI 不需要自己
    再組一份預覽，也就不可能與實印不一致。
    """

    printer: str
    item_id: str
    item_name: str
    template_id: str
    width_mm: float
    height_mm: float
    pixel_width: int
    pixel_height: int
    dpi: int
    pdf_width_mm: float
    pdf_height_mm: float
    html: str = ""


class PrinterOut(BaseModel):
    """可用的 Windows 印表機。"""

    name: str
    is_default: bool


class PrintSettingsOut(BaseModel):
    """列印設定：預設印表機 + 預設範本。

    回應**不含** `/api/printers` 的結果：那會隨 Windows 狀態變動，
    由 UI 另外呼叫 `/api/printers` 取得。這裡只給「使用者選了什麼」。
    """

    printer: str | None = None
    template_id: str | None = None
    exists: bool = False
    #: 設定檔讀不到時的原因。正常情況是 None。
    error: str | None = None
    config_file: str = f"tools/{print_config.CONFIG_FILENAME}"


class PrintSettingsUpdate(BaseModel):
    """儲存列印設定。

    兩個欄位都接受 null：null 代表「不要預設」，UI 會退回 Windows 預設
    印表機與清單第一個範本。
    """

    printer: str | None = None
    template_id: str | None = None


class ItemDetail(BaseModel):
    """§5：詳情含 observations、photos、identifiers、suggestions 數量。"""

    item: ItemOut
    observations: list[ObservationOut]
    photos: list[PhotoOut]
    identifiers: list[IdentifierOut]
    suggestions: list[SuggestionOut]
    suggestion_counts: dict[str, int]


class InboxEntryOut(BaseModel):
    relative: str
    captured_at: str | None
    captured_from: str
    bytes: int


class InboxGroupOut(BaseModel):
    index: int
    captured_at: str | None
    captured_from: str
    entries: list[InboxEntryOut]


class InboxListing(BaseModel):
    entries: list[InboxEntryOut]
    count: int


class InboxIntakeRequest(BaseModel):
    """選定要建檔的檔案。files 是 GET /api/inbox 回傳的 relative 路徑。"""

    files: list[str] = Field(min_length=1)
    #: 傳入就加到既有商品（重新觀測），不傳則開新的 Item。
    item_id: str | None = None
    kind: str = "intake"
    note: str = ""
    actor: str = "user"


class SkippedFile(BaseModel):
    relative: str


class InboxIntakeOut(BaseModel):
    item_id: str | None
    observation_id: str | None
    archived: list[PhotoOut]
    skipped: list[SkippedFile] = Field(default_factory=list)


class AiSettingsOut(BaseModel):
    """GET /api/settings/ai 的回應。

    刻意沒有 api_key 欄位，也不放任何可以反推出 key 的片段。要看有沒有設定
    看 configured；要真的用 key 請在 server 端讀檔。
    """

    provider: str
    configured: bool
    model: str
    #: 實際會打到的 base URL。公開資訊，不是秘密。
    base_url: str
    default_model: str
    #: 已知 provider 的預設 base URL，供前端切換 provider 時帶入。
    presets: dict[str, str]
    #: 請求是否來自本機 loopback（只用於顯示提示）。
    is_loopback: bool
    #: 任何能連到這台 server 的裝置都能改設定 —— 這台 server
    #: 刻意只服務受信任區網，信任模型與「區網可讀寫所有商品
    #: 資料」一致（見 shop/settings.py 的 docstring）。
    can_edit: bool
    #: 僅供使用者知道設定存在哪，不是秘密。
    config_file: str


class AiSettingsUpdate(BaseModel):
    """POST /api/settings/ai 的請求。

    `api_key` 留空或 None → **保留原本的 key**（密碼欄留白不是清除）。
    要清除請呼叫 POST /api/settings/ai/clear-key。
    `provider` / `base_url` 留空或 None → 保留原本的。
    """

    model: str | None = None
    api_key: str | None = None
    provider: str | None = None
    base_url: str | None = None


class AiSettingsSaved(BaseModel):
    provider: str
    configured: bool
    model: str
    base_url: str
    #: 存了什麼，不存 key 本身。
    api_key_changed: bool = False
    model_changed: bool = False
    provider_changed: bool = False
    base_url_changed: bool = False


class AiApiTestResult(BaseModel):
    ok: bool
    model: str
    detail: str = ""


class HealthOut(BaseModel):
    status: str
    schema_version: str


class StatsOut(BaseModel):
    counts: dict[str, int]
    recent: list[EventOut]
    #: UI 篩選下拉選單需要的清單；不放前端是因為前端不該硬寫分類與狀態值，
    #: 硬寫會和 DDL 的 CHECK 漂移。
    categories: list[str] = Field(default_factory=list)


class IdentifierLookupOut(BaseModel):
    value: str
    normalized: str
    matches: list[IdentifierOut]


def _from(row: Any, model: type) -> Any:
    return model(**{field: getattr(row, field) for field in model.model_fields})


#: dataclass → 回應模型。欄位名一致，所以直接照 model_fields 取值。
_OUT_MODELS: dict[type, type[BaseModel]] = {
    Item: ItemOut,
    Observation: ObservationOut,
    Photo: PhotoOut,
    Identifier: IdentifierOut,
    Suggestion: SuggestionOut,
    Event: EventOut,
    Template: TemplateOut,
}


def to_out(row: Any) -> BaseModel:
    model = _OUT_MODELS.get(type(row))
    if model is None:
        raise TypeError(f"不认识的資料列型別：{type(row).__name__}")
    return _from(row, model)


def to_outs(rows: list[Any]) -> list[Any]:
    return [to_out(row) for row in rows]

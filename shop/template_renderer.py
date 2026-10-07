"""Template Renderer：將 Template 與 Item 資料結合，產生渲染後的 HTML。

架構：
Item → View Model → Binding Resolver → Renderer → Rendered HTML

安全性：
- Template 被視為不可信輸入，只透過 allowlisted binding 存取資料
- 所有文字值經過 HTML escaping
- 圖片 binding 經過受控的 photo resolution
- 不執行 JavaScript、不存取任意 DB 欄位
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from html.parser import HTMLParser
from datetime import datetime
from urllib.parse import quote

from .config import Config
from .errors import ValidationError
from .models import Item, Template
from .repo import Repository
from .template_validator import ALLOWED_BINDING_FIELDS


#: 沒有結束標籤的元素，渲染時不要補 </img> 這種無效標記。
VOID_ELEMENTS: frozenset[str] = frozenset((
    "img", "br", "hr", "col", "source", "wbr",
))


# ----------------------------------------------------------------------
# View Model：只暴露允許的欄位
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TemplateViewModel:
    """Template 可存取的 Item 資料視圖。

    只包含 ALLOWED_BINDINGS 中定義的欄位。
    """

    id: str
    name: str
    brand: str
    model: str
    category: str
    quantity: str
    condition: str
    notes: str
    primary_photo: str  # 相對 URL 或空字串
    today: str = ""

    @classmethod
    def from_item(cls, item: Item, repo: Repository, config: Config) -> TemplateViewModel:
        """從 Item 建立 View Model。

        primary_photo 取最早的 original 照片。路徑沿用 /files/{相對路徑}
        這個既有的受控檔案服務（api.py 的 /files/{path} 會再確認
        目標落在 files/ 或 inbox/ 子樹內），所以這裡不做額外拼接規則，
        只把 DB 存的相對路徑原樣交出去。
        """
        photos = repo.list_photos(item_id=item.id, role="original", limit=1)
        primary_photo = ""
        if photos:
            # 相對路徑在建檔時已過 _check_relative_path（不可為絕對路徑、
            # 不可含 ..），此處只做 URL編碼讓含空白/# 的檔名也能正確解析。
            filename = photos[0].filename.strip("/")
            primary_photo = "/files/" + quote(filename, safe="/")

        # 專案日期一律採伺服器本機時間，格式固定為 YYYY/MM/DD
        today = datetime.now().strftime("%Y/%m/%d")

        return cls(
            id=item.id,
            name=item.name or "",
            brand=item.brand or "",
            model=item.model or "",
            category=item.category or "",
            quantity=str(item.quantity),
            condition=item.condition or "",
            notes=item.notes or "",
            primary_photo=primary_photo,
            today=today,
        )

    def get_field(self, field: str) -> str:
        """取得 binding 對應的值。

        Binding 格式為 "item.<field>"。這裡是渲染期的第二道防線：
        只認 validator 同一份 allowlist（ALLOWED_BINDING_FIELDS），
        絕不對任意字串做 getattr。
        """
        if field.startswith("item."):
            field = field[5:]
        if field not in ALLOWED_BINDING_FIELDS:
            # 未知 binding 不渲染，也不猜測修復（validator 應該擋在存檔前）。
            return ""
        value = getattr(self, field, "")
        return "" if value is None else str(value)


# ----------------------------------------------------------------------
# Binding Resolver：解析 HTML 中的 data-bind
# ----------------------------------------------------------------------


class TemplateRenderer(HTMLParser):
    """將 Template HTML 與 View Model 結合，輸出渲染後的 HTML。

    處理規則：
    - <tag data-bind="item.field">…</tag> → 整個元素的內容換成欄位值
      （HTML escaped），元素內既有的靜態內容會被丟棄
    - <tag data-bind-src="item.field"> → src 屬性換成欄位值
    - 移除所有 data-bind / data-bind-src 屬性
    - 其他屬性、靜態文字、註解、doctype 原樣保留（值會 HTML escape）
    """

    def __init__(self, view_model: TemplateViewModel) -> None:
        super().__init__()
        self.view_model = view_model
        self.output: list[str] = []
        # 綁定元素的取代狀態。用深度而不是布林，否則 <div data-bind="item.name">
        # 裡面再套子標籤時會把值灌到錯的位置。
        self._bind_tag: str | None = None
        self._bind_value: str = ""
        self._bind_depth: int = 0

    # -- helpers ---------------------------------------------------------

    def _render_attrs(self, attrs: list[tuple[str, str | None]]) -> str:
        parts = []
        for name, value in attrs:
            if value is None:
                parts.append(name)
            else:
                parts.append(f'{name}="{html.escape(value, quote=True)}"')
        return "".join(f" {part}" for part in parts)

    # -- HTMLParser hooks -----------------------------------------------

    def handle_decl(self, decl: str) -> None:
        # <!doctype html> 必須保留：preview 走 iframe srcdoc，掉了 doctype
        # 會變成 quirks mode，版面跟作者寫的不一樣。
        if not self._bind_tag:
            self.output.append(f"<!{decl}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        bind_src = attrs_dict.pop("data-bind-src", None)
        bind_text = attrs_dict.pop("data-bind", None)

        # 已經在綁定元素內：整段內容都會被欄位值取代，直接吞掉。
        if self._bind_tag is not None:
            self._bind_depth += 1
            return

        if bind_src:
            attrs_dict["src"] = self.view_model.get_field(bind_src)
        self.output.append(f"<{tag}{self._render_attrs(list(attrs_dict.items()))}>")

        if bind_text:
            self._bind_tag = tag
            self._bind_value = bind_text
            self._bind_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self._bind_tag is not None:
            self._bind_depth -= 1
            if self._bind_depth > 0:
                # 內層元素的結束標籤，跟內容一起被丟棄。
                return
            self._bind_tag = None
            self.output.append(
                html.escape(self.view_model.get_field(self._bind_value))
            )
        if tag not in VOID_ELEMENTS:
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        # 綁定元素內的靜態文字會被欄位值取代。
        if self._bind_tag is None:
            self.output.append(data)

    def handle_comment(self, data: str) -> None:
        if self._bind_tag is None:
            self.output.append(f"<!--{data}-->")

    def handle_entityref(self, name: str) -> None:
        if self._bind_tag is None:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._bind_tag is None:
            self.output.append(f"&#{name};")

    def handle_pi(self, data: str) -> None:
        # <?...> 在 HTML 裡是 bogus comment，原樣輸出即可。
        if self._bind_tag is None:
            self.output.append(f"<?{data}>")

    def render(self) -> str:
        return "".join(self.output)


# ----------------------------------------------------------------------
# 高層 Render 函式
# ----------------------------------------------------------------------


class RenderError(ValidationError):
    """渲染錯誤。"""
    pass


def render_template(
    template: Template,
    item: Item,
    repo: Repository,
    config: Config,
) -> str:
    """渲染 Template。

    Args:
        template: Template 實體
        item: 目標商品
        repo: Repository 實例（用於查詢照片等）
        config: Config 實例（用於構建 URL）

    Returns:
        渲染後的 HTML 字串

    Raises:
        RenderError: 渲染失敗
    """
    try:
        view_model = TemplateViewModel.from_item(item, repo, config)
        renderer = TemplateRenderer(view_model)
        renderer.feed(template.html)
        renderer.close()
        return renderer.render()
    except Exception as exc:
        raise RenderError(f"Template 渲染失敗: {exc}") from exc


def render_template_preview(
    template: Template,
    item: Item,
    repo: Repository,
    config: Config,
) -> str:
    """渲染預覽用 HTML。

    Phase 1 的預覽就是同一份渲染結果（沒有額外框線或浮水印）。
    與 render_template 完全唯讀：不修改 Template、不修改 Item、
    不寫任何資料表，也不產生 events 或 suggestions。
    """
    return render_template(template, item, repo, config)
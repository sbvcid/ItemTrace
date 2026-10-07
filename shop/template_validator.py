"""Template Validator：驗證 HTML/CSS Template 的安全性與合法性。

Template 被視為「不可信輸入」，必須在儲存前經過嚴格驗證：
- 只允許明確 allowlist 的 HTML 標籤
- 拒絕 script、iframe、event handlers 等高風險內容
- CSS 禁止 @import、外部 url()
- 所有 data-bind / data-bind-src 必須在 field registry 中
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from .errors import ValidationError


# ----------------------------------------------------------------------
# 允許的標籤與屬性
# ----------------------------------------------------------------------

#: 明確允許的標籤。任何不在這裡的一律拒絕 —— 含 script/iframe/form/base/
#: link/meta（外部樣式表、favicon、meta refresh 都會造成外部請求或重新導頁）。
ALLOWED_TAGS: frozenset[str] = frozenset((
    "html", "head", "body", "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "img", "strong", "em", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
    "section", "article", "header", "footer", "hr", "style", "title",
    "br", "b", "i", "u", "small", "sup", "sub", "blockquote", "pre", "code",
    "a",
))

#: 明確拒絕的標籤（錯誤訊息用）。允許清單已經不包含它們，這裡是為了
#: 讓「為什麼被擋」講得清楚，不是第二套授權來源。
FORBIDDEN_TAGS: frozenset[str] = frozenset((
    "script", "iframe", "object", "embed", "form", "link", "base", "meta",
    "input", "button", "select", "textarea", "option", "label",
    "applet", "frameset", "frame", "noscript", "svg", "math", "portal",
))

ALLOWED_ATTRS: frozenset[str] = frozenset((
    "class", "id", "style", "alt", "title", "width", "height",
    "data-bind", "data-bind-src", "src", "href",
    "colspan", "rowspan", "scope",
))

FORBIDDEN_ATTR_PREFIXES: tuple[str, ...] = ("on",)  # onclick, onload, etc.
FORBIDDEN_URL_SCHEMES: tuple[str, ...] = ("javascript:", "data:", "file:", "http:", "https:")

#: Template 自己寫的 URL 只允許「同源相對路徑」或純錨點。
#: 這一條同時擋掉 protocol-relative（``//evil.com/x.png``）、各種 scheme，
#: 以及 ``data:``。Template 要放圖只能走 ``data-bind-src``。
SAFE_RELATIVE_URL = re.compile(r"^(?:#|/)?[A-Za-z0-9._~\-]+(?:/[A-Za-z0-9._~\-]*)*$")

#: CSS 禁止模式。``url()`` 一律禁止：Phase 1 的圖片只能來自
#: ``item.primary_photo`` binding，所以沒有任何正當理由需要 CSS url()，
#: 一律拒絕可同時消除 http/https/file/data/protocol-relative/相對路徑
#: 這整類外部資源載入。
CSS_FORBIDDEN_PATTERNS = (
    re.compile(r"@import\b", re.IGNORECASE),
    re.compile(r"@charset\b", re.IGNORECASE),
    re.compile(r"@namespace\b", re.IGNORECASE),
    re.compile(r"url\s*\(", re.IGNORECASE),
    re.compile(r"expression\s*\(", re.IGNORECASE),
    re.compile(r"(?:javascript|vbscript|data|file|https?)\s*:", re.IGNORECASE),
    re.compile(r"behaviou?r\s*[:=]", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(?:script|iframe|object|embed)", re.IGNORECASE),
)

# Phase 1 允許的 binding fields（依實際 Item schema 與渲染情境）
ALLOWED_BINDINGS: frozenset[str] = frozenset((
    "item.id",
    "item.name",
    "item.brand",
    "item.model",
    "item.category",
    "item.quantity",
    "item.condition",
    "item.notes",
    "item.primary_photo",
    "today",
))

#: 同一份 registry 的短名版本，Renderer 用它做第二道防線
#: （validator 擋存檔，renderer 擋渲染 —— 兩層都只認 allowlist）。
ALLOWED_BINDING_FIELDS: frozenset[str] = frozenset(
    binding[5:] if binding.startswith("item.") else binding
    for binding in ALLOWED_BINDINGS
)

#: data-bind-src 只接受圖片欄位。
IMAGE_BINDINGS: frozenset[str] = frozenset(("item.primary_photo",))


class TemplateValidator(HTMLParser):
    """HTML 模板驗證器。

    繼承 HTMLParser，逐標籤檢查：
    - 標籤是否在 allowlist
    - 屬性是否合法
    - CSS 是否包含禁止模式
    - data-bind / data-bind-src 是否在 registry
    """

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []
        self._in_style = False
        self._style_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # 檢查標籤
        if tag in FORBIDDEN_TAGS:
            self.errors.append(f"禁止的標籤: <{tag}>")
            return
        if tag not in ALLOWED_TAGS:
            self.errors.append(f"不允許的標籤: <{tag}>")
            return

        # 檢查屬性
        for attr_name, attr_value in attrs:
            if attr_name.startswith(FORBIDDEN_ATTR_PREFIXES):
                self.errors.append(f"禁止的事件屬性: {attr_name}")
                continue

            if attr_name not in ALLOWED_ATTRS:
                self.errors.append(f"不允許的屬性: {attr_name}")
                continue

            # 檢查 binding 屬性
            if attr_name in ("data-bind", "data-bind-src"):
                kind = "image" if attr_name == "data-bind-src" else "text"
                try:
                    validate_binding(attr_value or "", kind)
                except ValidationError as exc:
                    self.errors.append(
                        f"{exc}（允許: {', '.join(sorted(ALLOWED_BINDINGS))}）"
                    )
                continue

            # 檢查 URL 屬性：Template 自己指定的 URL 只能是同源相對路徑或錨點。
            # 圖片請用 data-bind-src="item.primary_photo"。
            if attr_name in ("src", "href") and attr_value is not None:
                candidate = attr_value.strip()
                lowered = candidate.lower()
                for scheme in FORBIDDEN_URL_SCHEMES:
                    if lowered.startswith(scheme):
                        self.errors.append(
                            f"禁止的 URL 協定: {attr_name}=\"{attr_value}\""
                        )
                        break
                else:
                    # 擋掉 protocol-relative（//host/...）與任何非相對參照
                    if not SAFE_RELATIVE_URL.match(candidate):
                        self.errors.append(
                            f"URL 必須是同源相對路徑或錨點: "
                            f"{attr_name}=\"{attr_value}\"；"
                            f"圖片請用 data-bind-src=\"item.primary_photo\""
                        )

            # inline style 也是 CSS，走同一套檢查
            if attr_name == "style" and attr_value:
                self._check_css(attr_value, where=f"{tag}[style]")

        # 標記進入 style 區塊
        if tag == "style":
            self._in_style = True
            self._style_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False
            self._check_css("".join(self._style_buffer), where="<style>")
            self._style_buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._style_buffer.append(data)

    def handle_comment(self, data: str) -> None:
        # 註解在舊引擎 / quirks mode 下可能被當成內容解析，也要擋。
        lowered = data.lower()
        for scheme in FORBIDDEN_URL_SCHEMES:
            if scheme in lowered:
                self.errors.append(f"註解中包含禁止的 URL 協定: {data[:50]}...")
                return
        self._check_css(data, where="註解")

    def _check_css(self, css: str, *, where: str = "CSS") -> None:
        for pattern in CSS_FORBIDDEN_PATTERNS:
            if pattern.search(css):
                self.errors.append(
                    f"{where} 包含禁止模式: {pattern.pattern}"
                )

    def validate(self, html: str) -> list[str]:
        """驗證 HTML，回傳錯誤清單（空清單 = 通過）。"""
        self.errors = []
        self._in_style = False
        self._style_buffer = []
        try:
            self.feed(html)
        except Exception as exc:
            self.errors.append(f"HTML 解析失敗: {exc}")
        self.close()
        return self.errors


def validate_template(html: str) -> None:
    """驗證 Template，失敗拋 ValidationError。"""
    validator = TemplateValidator()
    errors = validator.validate(html)
    if errors:
        raise ValidationError("Template 驗證失敗:\n" + "\n".join(f"  - {e}" for e in errors))


def validate_binding(binding: str, kind: str) -> None:
    """驗證單一 binding 是否在 registry 中。

    Args:
        binding: binding 值，如 "item.name"
        kind: "text" 或 "image"，決定檢查 data-bind 還是 data-bind-src
    """
    if binding not in ALLOWED_BINDINGS:
        label = "圖片" if kind == "image" else "文字"
        raise ValidationError(f"未知的{label} binding: {binding}")
    if kind == "image" and binding not in IMAGE_BINDINGS:
        raise ValidationError(f"{binding} 不是可綁定的圖片欄位")
    if kind not in ("text", "image"):
        raise ValidationError(f"未知的 binding 類型: {kind}")
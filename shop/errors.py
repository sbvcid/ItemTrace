"""資料存取層的領域例外。

API 層（階段 4）直接把這些例外翻成 HTTP 狀態碼，所以分類刻意對齊語意：

    NotFoundError   → 404
    ConflictError   → 409
    ValidationError → 400
    ShopError       → 500
"""

from __future__ import annotations


class ShopError(Exception):
    """本專案所有資料存取例外的基底類別。"""


class NotFoundError(ShopError):
    """指定的資料不存在。"""


class ValidationError(ShopError):
    """值不合法：欄位名稱錯誤、列舉值超出範圍、JSON 格式錯誤等。"""


class ConflictError(ShopError):
    """與既有資料衝突，例如同一商品重複的識別碼。"""

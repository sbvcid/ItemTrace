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


class PayloadTooLargeError(ShopError):
    """請求或檔案超過資源上限（SR-2／F4）→ 413。"""


class NotFoundError(ShopError):
    """指定的資料不存在。"""


class ValidationError(ShopError):
    """值不合法：欄位名稱錯誤、列舉值超出範圍、JSON 格式錯誤等。"""


class ConflictError(ShopError):
    """與既有資料衝突，例如同一商品重複的識別碼。"""


class PurgeError(ShopError):
    """永久刪除的前置檢查或檔案清理失敗。

    訊息一定說明目前的真實狀態：資料庫是否已刪除、哪些路徑還在，
    讓使用者能自行清理；不把「刪不掉」假裝成成功。API 層回 500。
    """

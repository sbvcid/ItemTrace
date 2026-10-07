"""列印設定（`tools/print_config.local.json`）的唯一格式定義。

這份檔案只存「長期設定」，不放任何機密：預設印表機名稱與預設範本 ID
都是本機狀態，不像 AI 的 api_key 需要保護。所以格式刻意做得很薄 ——
兩個欄位、一個 JSON 檔，沒有巢狀結構。

為什麼不放進 `config.json`
-------------------------
`config.json` 是 DATA_ROOT 層級的基礎設施（資料在哪、server 綁哪個位址），
由 `shop/config.py` 管、CLI 與 server 共用，而且沒有 API（只能手改檔案）。
預設印表機／範本是「在網頁上設定的功能選項」，跟 AI 設定同一個性質，
所以跟著 `shop/ai_config.py` 的模式走：獨立檔案 + 獨立 router。

設計上刻意保守的地方
--------------------
* 設定的印表機名稱**不驗證**存不存在。Windows 上印表機可能被改名、被刪，
  硬擋只會讓使用者改了設定卻存不進去。真正要送印時才由
  `print_backend.resolve_printer()` 檢查並給明確錯誤。
* 範本 ID 同理。用一個已刪除的範本 ID 存進來是允許的，
  列印時會得到 404，使用者就知道該換一個了。
* 讀檔失敗（JSON 語法錯）不丟例外到 API 層以外的預設路徑 ——
  `read_settings()` 會回傳帶 `error` 的結果，頁面直接顯示原因，
  使用者可以覆寫掉壞掉的檔案。這跟 ai_config 會 raise 的做法不同，
  因為列印設定沒有機密、也沒有「讀不到就沒辦法用」的必要。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: 與 ai_config 相同的慣例：放在專案根目錄的 tools/ 下。
PRINT_DIRNAME = "tools"
CONFIG_FILENAME = "print_config.local.json"


def project_root(start: Path | None = None) -> Path:
    """從 shop/ 往上找專案根目錄（含 shop/ 與 tools/ 的那層）。"""
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        if (parent / "shop").is_dir() and (parent / PRINT_DIRNAME).is_dir():
            return parent
    return here.parent.parent


def config_path(root: Path | None = None) -> Path:
    """設定檔路徑。只能由程式決定，瀏覽器不能指定。"""
    return (root or project_root()) / PRINT_DIRNAME / CONFIG_FILENAME


@dataclass(frozen=True)
class PrintSettings:
    """列印設定。

    `printer` / `template_id` 都可以是 None（尚未設定），那時 UI 應該
    退回「Windows 預設印表機」與「清單第一個範本」，而不是報錯。
    """

    printer: str | None
    template_id: str | None
    exists: bool
    path: Path
    #: 檔案壞掉時的原因。正常情況是 None。
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "printer": self.printer,
            "template_id": self.template_id,
            "exists": self.exists,
            "error": self.error,
        }


def _clean(value: object) -> str | None:
    """把任意 JSON 值收成「非空字串或 None」。"""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def read_settings(path: Path | str | None = None) -> PrintSettings:
    """讀設定。檔案不存在不算錯，只是未設定。

    檔案存在但內容不是 JSON 物件時，也不丟例外 —— 回傳帶 `error` 的
    結果，讓頁面顯示原因而不是 500。
    """
    target = Path(path) if path is not None else config_path()
    if not target.exists():
        return PrintSettings(None, None, False, target)

    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return PrintSettings(
            None, None, True, target,
            f"{target.name} 讀取失敗：{exc}",
        )
    if not isinstance(data, dict):
        return PrintSettings(
            None, None, True, target,
            f"{target.name} 的內容必須是 JSON 物件。",
        )

    return PrintSettings(
        printer=_clean(data.get("printer")),
        template_id=_clean(data.get("template_id")),
        exists=True,
        path=target,
    )


def save_settings(
    printer: str | None = None,
    template_id: str | None = None,
    path: Path | str | None = None,
) -> PrintSettings:
    """寫回設定。

    兩個參數都接受 None，代表「清除這個預設」：None 會寫成 JSON null，
    與「保持原樣」不同 —— 這裡刻意不提供「保持原樣」語義，因為設定頁
    送出的一定是使用者看到的完整表單。
    """
    target = Path(path) if path is not None else config_path()
    payload = {
        "printer": _clean(printer),
        "template_id": _clean(template_id),
    }
    target.parent.mkdir(parents=True, exist_ok=True)

    # atomic write：先寫暫存檔再 rename，避免中途中斷留下半個 JSON
    handle, temp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=target.name, suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temp_name, target)
    except Exception:
        # 換不成功就把暫存檔收掉，不要留在專案目錄裡
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

    return PrintSettings(
        printer=payload["printer"],
        template_id=payload["template_id"],
        exists=True,
        path=target,
    )
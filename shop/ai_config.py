"""AI adapter 設定檔（`tools/ai_config.local.json`）的唯一格式定義。

為什麼放在 shop/ 裡：只有一份地方知道這個檔案長什麼樣、怎麼驗、怎麼寫。
`tools/analyze_item.py` 與 `/settings` 頁面都 import 這個模組，不各自刻一份
規則 —— 否則兩邊很快就會漂移。

這個模組刻意「不知道」OpenRouter、Vision、prompt 那些事，只管檔案：

  * 路徑由程式決定，瀏覽器不能指定
  * `AiSettings` 型別裡沒有 api_key 欄位 —— 就算不小心被序列化也不會漏
  * 回傳給瀏覽器的內容永遠不含 key

AI 的設定和 ItemTrace 的 runtime 設定是兩回事：那份在 `config.json`
（DATA_ROOT、server_host），這份在 `tools/ai_config.local.json`（一把
給外部工具用的 secret）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PROVIDER = "openrouter"
DEFAULT_MODEL = "qwen/qwen3.8-27b:free"

AI_DIRNAME = "tools"
CONFIG_FILENAME = "ai_config.local.json"
EXAMPLE_FILENAME = "ai_config.example.json"

MISSING_CONFIG = f"""\
找不到 {CONFIG_FILENAME}

第一次使用請先建立設定檔：
    複製 tools/{EXAMPLE_FILENAME}
      → tools/{CONFIG_FILENAME}
    把裡面的 api_key 換成自己的 OpenRouter API key
    （model 不填就用預設值）

這個檔案已被 .gitignore 排除，不會被 commit。
也可以直接開 http://127.0.0.1:8731/settings 在網頁裡設定。"""


class AiConfigError(Exception):
    """設定檔有問題（格式錯、缺 key）。訊息裡永遠不含 key 本身。"""


@dataclass(frozen=True)
class AiConfig:
    """給「真的要把 key 拿去用」的程式。"""

    api_key: str
    model: str


@dataclass(frozen=True)
class AiSettings:
    """給「要顯示給人看」的程式。

    刻意沒有 api_key 欄位 —— 少一個欄位就少一個洩漏的機會。
    要知道有沒有設定看 configured，要用真的 key 請呼叫 load_config()。
    """

    provider: str
    model: str
    configured: bool
    exists: bool
    path: Path


# ----------------------------------------------------------------------
# 路徑：只由程式決定
# ----------------------------------------------------------------------


def project_root(start: Path | None = None) -> Path:
    """從 shop/ 往上找專案根目錄（含 shop/ 與 tools/ 的那層）。"""
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        if (parent / "shop").is_dir() and (parent / AI_DIRNAME).is_dir():
            return parent
    return here.parent.parent


def config_path(root: Path | None = None) -> Path:
    return (root or project_root()) / AI_DIRNAME / CONFIG_FILENAME


def example_path(root: Path | None = None) -> Path:
    return (root or project_root()) / AI_DIRNAME / EXAMPLE_FILENAME


# ----------------------------------------------------------------------
# 讀
# ----------------------------------------------------------------------


def _parse(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise AiConfigError(f"讀不到 {path.name}：{exc.strerror}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # 整份內容含 key，只報錯不行銷毀它
        raise AiConfigError(
            f"{path.name} 不是合法 JSON（第 {exc.lineno} 行）：{exc.msg}"
        ) from None
    if not isinstance(data, dict):
        raise AiConfigError(f"{path.name} 的內容必須是 JSON 物件")
    return data


def _model_of(data: dict, filename: str) -> str:
    model = data.get("model")
    if model is not None and not isinstance(model, str):
        raise AiConfigError(
            f"{filename} 的 model 必須是字串（或留空用預設值），"
            f"得到 {type(model).__name__}"
        )
    return (model or "").strip() or DEFAULT_MODEL


def _key_of(data: dict) -> str:
    key = data.get("api_key")
    if key is None or (isinstance(key, str) and not key.strip()):
        return ""
    if not isinstance(key, str):
        raise AiConfigError("api_key 必須是字串")
    return key.strip()


def read_settings(path: Path | str | None = None) -> AiSettings:
    """讀設定狀態。檔案不存在不算錯 —— 只是未設定。

    只有檔案本身壞掉（JSON 語法錯、型別錯）才會拋錯。
    """
    target = Path(path) if path is not None else config_path()
    if not target.exists():
        return AiSettings(
            provider=PROVIDER, model=DEFAULT_MODEL,
            configured=False, exists=False, path=target,
        )
    data = _parse(target)
    return AiSettings(
        provider=PROVIDER,
        model=_model_of(data, target.name),
        configured=bool(_key_of(data)),
        exists=True,
        path=target,
    )


def load_config(path: Path | str | None = None) -> AiConfig:
    """真的要拿 key 去呼叫 provider 時用。缺設定就明確停下來。"""
    target = Path(path) if path is not None else config_path()
    if not target.exists():
        raise AiConfigError(MISSING_CONFIG)
    data = _parse(target)
    key = _key_of(data)
    if not key:
        raise AiConfigError(
            f"{target.name} 缺少 api_key（或不是非空字串）。"
            "開 http://127.0.0.1:8731/settings 設定，或直接編輯該檔案。"
        )
    return AiConfig(api_key=key, model=_model_of(data, target.name))


# ----------------------------------------------------------------------
# 寫（只有 server 端會呼叫；路徑固定由程式決定）
# ----------------------------------------------------------------------


def save_settings(
    api_key: str | None,
    model: str | None,
    path: Path | str | None = None,
) -> AiSettings:
    """寫回設定。

    `api_key` 為 None 或空白 → **保留原本的 key**。密碼欄留白不是清除，
    要清除請呼叫 clear_api_key()。

    `model` 為 None 或空白 → 用預設值。
    """
    target = Path(path) if path is not None else config_path()
    existing = _parse(target) if target.exists() else {}
    previous = _key_of(existing)

    incoming = (api_key or "").strip()
    if not incoming and not previous:
        raise AiConfigError(
            "尚未設定 API key。請填入 OpenRouter API key，"
            "或只修改 model（需先有既存的 key）。"
        )

    key = incoming or previous
    chosen = (model or "").strip() or DEFAULT_MODEL
    if not isinstance(chosen, str):
        raise AiConfigError("model 必須是字串")

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"api_key": key, "model": chosen}
    _write_private(target, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    return AiSettings(
        provider=PROVIDER, model=chosen, configured=True, exists=True, path=target
    )


def clear_api_key(path: Path | str | None = None) -> AiSettings:
    """清除 key，但保留 model。

    留空密碼欄 ≠ 清除 —— 這是明確的動作，避免使用者只是按了儲存就把 key 弄丟。
    """
    target = Path(path) if path is not None else config_path()
    chosen = DEFAULT_MODEL
    if target.exists():
        chosen = _model_of(_parse(target), target.name)
    _write_private(
        target, json.dumps({"model": chosen}, indent=2, ensure_ascii=False) + "\n"
    )
    return AiSettings(
        provider=PROVIDER, model=chosen, configured=False, exists=True, path=target
    )


def _write_private(target: Path, text: str) -> None:
    """先寫暫存檔再換名，中途失敗不會留下半個設定檔。"""
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    try:  # 只有在支援的地方收緊權限
        target.chmod(0o600)
    except OSError:
        pass


# ----------------------------------------------------------------------
# 遮蔽：任何要顯示給人看的文字都先過這裡
# ----------------------------------------------------------------------

_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def redact(text: str, secret: str | None = None) -> str:
    """把 key 從字串裡塗掉。

    就算不認識那把 key（settings API 只有 configured 布林，沒有 key），
    任何看起來像 key 的字串還是會被蓋掉。
    """
    if secret and secret in text:
        text = text.replace(secret, "***")
    return _KEY_PATTERN.sub("sk-***", text)

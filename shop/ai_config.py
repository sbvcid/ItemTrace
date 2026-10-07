"""AI adapter 設定檔（`tools/ai_config.local.json`）的唯一格式定義。

為什麼放在 shop/ 裡：只有一份地方知道這個檔案長什麼樣、怎麼驗、怎麼寫。
`tools/analyze_item.py`、`/settings` 頁面與 server 端的 AI 分析端點都
import 這個模組，不各自刻一份規則 —— 否則幾邊很快就會漂移。

這個模組刻意「不知道」Vision、prompt 那些事，只管檔案：

  * 路徑由程式決定，瀏覽器不能指定
  * `AiSettings` 型別裡沒有 api_key 欄位 —— 就算不小心被序列化也不會漏
  * 回傳給瀏覽器的內容永遠不含 key

provider 與 base_url 是可選欄位：舊檔案沒有就當 openrouter（向後相容）。
兩者合起來決定 AI 服務的 chat completions 端點 —— 請求本身是
OpenAI Chat Completions 相容格式，所以任何相容 API 都能用
（provider='custom' + 自填 base_url，例如 Google Gemini 的
OpenAI 相容端點）。

AI 的設定和 ItemTrace 的 runtime 設定是兩回事：那份在 `config.json`
（DATA_ROOT、server_host），這份在 `tools/ai_config.local.json`（一把
給外部工具用的 secret）。
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

#: 預設 provider。舊設定檔沒有 provider 欄位時用它（向後相容）。
PROVIDER = "openrouter"

#: 使用者自填端點。base_url 一定要自己給。
CUSTOM = "custom"

#: 已知 provider 的預設 base URL（都是 OpenAI Chat Completions 相容層）。
PROVIDER_BASE_URLS = {
    PROVIDER: "https://openrouter.ai/api/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
}

#: 白名單：预设 + custom。
KNOWN_PROVIDERS = tuple(PROVIDER_BASE_URLS) + (CUSTOM,)

DEFAULT_MODEL = "qwen/qwen3.8-27b:free"
DEFAULT_BASE_URL = PROVIDER_BASE_URLS[PROVIDER]

AI_DIRNAME = "tools"
CONFIG_FILENAME = "ai_config.local.json"
EXAMPLE_FILENAME = "ai_config.example.json"

MISSING_CONFIG = f"""\
找不到 {CONFIG_FILENAME}

第一次使用請先建立設定檔：
    複製 tools/{EXAMPLE_FILENAME}
      → tools/{CONFIG_FILENAME}
    把裡面的 api_key 換成自己的 API key
    （provider / base_url / model 不填就用預設值）

這個檔案已被 .gitignore 排除，不會被 commit。
也可以直接開 http://127.0.0.1:8731/settings 在網頁裡設定。"""


class AiConfigError(Exception):
    """設定檔有問題（格式錯、缺 key）。訊息裡永遠不含 key 本身。"""


@dataclass(frozen=True)
class AiConfig:
    """給「真的要把 key 拿去用」的程式。"""

    api_key: str
    model: str
    provider: str = PROVIDER
    base_url: str = DEFAULT_BASE_URL


@dataclass(frozen=True)
class AiSettings:
    """給「要顯示給人看」的程式。

    刻意沒有 api_key 欄位 —— 少一個欄位就少一個洩漏的機會。
    要知道有沒有設定看 configured，要用真的 key 請呼叫 load_config()。
    """

    provider: str
    model: str
    base_url: str
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
# 驗證：provider 白名單、base_url 必須是 http/https
# ----------------------------------------------------------------------


def _validated_provider(value: str | None) -> str:
    if value is None:
        return PROVIDER
    provider = value.strip()
    if provider not in KNOWN_PROVIDERS:
        raise AiConfigError(
            f"provider 必須是 {' / '.join(KNOWN_PROVIDERS)}，得到 {provider!r}"
        )
    return provider


def _validated_base_url(value: str | None) -> str:
    url = (value or "").strip()
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AiConfigError(f"base_url 必須是 http/https URL，得到 {url!r}")
    return url


def resolve_base_url(provider: str | None, base_url: str | None) -> str:
    """provider 決定預設 base_url；custom 一定要自己給。"""
    chosen = _validated_provider(provider)
    url = _validated_base_url(base_url)
    if not url:
        url = PROVIDER_BASE_URLS.get(chosen, "")
    if not url:
        raise AiConfigError(
            "provider='custom' 必須提供 base_url（任何 OpenAI 相容 API 的"
            "端點基址，例如 https://generativelanguage.googleapis.com/v1beta/openai/）"
        )
    return url


def chat_endpoint(provider: str | None, base_url: str | None) -> str:
    """解析出完整的 chat completions 端點。設定讀取與 API 測試共用這條規則。"""
    return resolve_base_url(provider, base_url).rstrip("/") + "/chat/completions"


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


def _provider_of(data: dict, filename: str) -> str:
    value = data.get("provider")
    if value is not None and not isinstance(value, str):
        raise AiConfigError(f"{filename} 的 provider 必須是字串")
    return _validated_provider(value)


def _base_url_of(data: dict, filename: str, provider: str) -> str:
    value = data.get("base_url")
    if value is not None and not isinstance(value, str):
        raise AiConfigError(f"{filename} 的 base_url 必須是字串")
    try:
        return resolve_base_url(provider, value)
    except AiConfigError as exc:
        raise AiConfigError(f"{filename}：{exc}") from None


def read_settings(path: Path | str | None = None) -> AiSettings:
    """讀設定狀態。檔案不存在不算錯 —— 只是未設定。

    只有檔案本身壞掉（JSON 語法錯、型別錯）才會拋錯。
    """
    target = Path(path) if path is not None else config_path()
    if not target.exists():
        return AiSettings(
            provider=PROVIDER, model=DEFAULT_MODEL,
            base_url=DEFAULT_BASE_URL,
            configured=False, exists=False, path=target,
        )
    data = _parse(target)
    provider = _provider_of(data, target.name)
    return AiSettings(
        provider=provider,
        model=_model_of(data, target.name),
        base_url=_base_url_of(data, target.name, provider),
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
    provider = _provider_of(data, target.name)
    return AiConfig(
        api_key=key,
        model=_model_of(data, target.name),
        provider=provider,
        base_url=_base_url_of(data, target.name, provider),
    )


# ----------------------------------------------------------------------
# 寫（只有 server 端會呼叫；路徑固定由程式決定）
# ----------------------------------------------------------------------


def save_settings(
    api_key: str | None,
    model: str | None,
    provider: str | None = None,
    base_url: str | None = None,
    path: Path | str | None = None,
) -> AiSettings:
    """寫回設定。

    `api_key` 為 None 或空白 → **保留原本的 key**。密碼欄留白不是清除，
    要清除請呼叫 clear_api_key()。

    `model` 為 None 或空白 → 用預設值。
    `provider` 為 None 或空白 → 保留原本（舊檔沒有就是 openrouter）。
    `base_url` 為 None 或空白 → 換 provider 時用新 provider 的預設值，
    否則保留原本。
    """
    target = Path(path) if path is not None else config_path()
    existing = _parse(target) if target.exists() else {}
    previous = _key_of(existing)

    incoming = (api_key or "").strip()
    if not incoming and not previous:
        raise AiConfigError(
            "尚未設定 API key。請填入 API key，"
            "或只修改 model（需先有既存的 key）。"
        )

    key = incoming or previous
    chosen_model = (model or "").strip() or DEFAULT_MODEL

    old_provider = _validated_provider(existing.get("provider"))
    chosen_provider = _validated_provider(provider or existing.get("provider"))
    explicit_base = (base_url or "").strip()
    if explicit_base:
        chosen_base = explicit_base
    elif chosen_provider != old_provider:
        # 換 provider 時不沿用舊端點：openrouter 的 URL 配給 Google 用
        # 是最常見的誤設，定向回到該 provider 的預設值。
        chosen_base = PROVIDER_BASE_URLS.get(chosen_provider, "")
    else:
        chosen_base = (existing.get("base_url") or "").strip()
    try:
        chosen_base = resolve_base_url(chosen_provider, chosen_base)
    except AiConfigError as exc:
        raise AiConfigError(f"base_url：{exc}") from None

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "api_key": key,
        "model": chosen_model,
        "provider": chosen_provider,
        "base_url": chosen_base,
    }
    _write_private(target, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    return AiSettings(
        provider=chosen_provider, model=chosen_model, base_url=chosen_base,
        configured=True, exists=True, path=target,
    )


def clear_api_key(path: Path | str | None = None) -> AiSettings:
    """清除 key，但保留 provider / base_url / model。

    留空密碼欄 ≠ 清除 —— 這是明確的動作，避免使用者只是按了儲存就把 key 弄丟。
    """
    target = Path(path) if path is not None else config_path()
    chosen = DEFAULT_MODEL
    provider = PROVIDER
    base_url = DEFAULT_BASE_URL
    if target.exists():
        data = _parse(target)
        provider = _provider_of(data, target.name)
        chosen = _model_of(data, target.name)
        base_url = _base_url_of(data, target.name, provider)
    _write_private(
        target,
        json.dumps(
            {"provider": provider, "base_url": base_url, "model": chosen},
            indent=2, ensure_ascii=False,
        ) + "\n",
    )
    return AiSettings(
        provider=provider, model=chosen, base_url=base_url,
        configured=False, exists=True, path=target,
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

#: sk- 是 OpenRouter / OpenAI 慣用的 key 前綴，AIza 是 Google 的。
_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{20,}")


def redact(text: str, secret: str | None = None) -> str:
    """把 key 從字串裡塗掉。

    就算不認識那把 key（settings API 只有 configured 布林，沒有 key），
    任何看起來像 key 的字串還是會被蓋掉。
    """
    if secret and secret in text:
        text = text.replace(secret, "***")
    return _KEY_PATTERN.sub("sk-***", text)

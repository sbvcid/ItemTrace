"""`/api/settings/ai` —— 在網頁上設定 OpenRouter API key 與 model。

安全性是這一頁的全部重點，所以先把規則寫在最前面：

1. **GET 永遠不回傳 key。** `shop/schemas.py` 的 AiSettingsOut 沒有
   api_key 欄位，回應組裝處也不碰 key —— 少一個欄位就少一個洩漏的機會。

2. **只有 loopback 可以改。** 本專案沒有登入系統，而 `server_host` 常被
   改成 `0.0.0.0` 讓手機連進來。若同一個 Wi-Fi 裡的任何人能改 API key，
   就等於他能動用你的 OpenRouter 帳號。所以寫入類的端點（存檔／清除／
   測試）只接受來自 127.0.0.1 / ::1 的請求。

   判斷用的是 `request.client.host` —— 那是 socket 的對端位址，由
   WebSocket/HTTP server 從連線本身取得。**不看 X-Forwarded-For**，
   實測過偽造該標頭不會改變 client.host（見 tests/test_settings_api.py）。

3. **API 不能指定路徑。** 設定檔位置由 `shop/ai_config.py` 決定，
   瀏覽器傳什麼 path／filename 都不進來。

4. **錯誤訊息不帶 key。**  provider 的錯誤會經過 ai_config.redact()。
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request

from fastapi import APIRouter, Request

from . import ai_config
from .ai_config import AiConfigError
from .errors import ValidationError
from .schemas import (
    AiApiTestResult,
    AiSettingsOut,
    AiSettingsSaved,
    AiSettingsUpdate,
)

router = APIRouter(tags=["settings"])

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
PROVIDER_TEST_TIMEOUT = 30


def is_loopback(request: Request) -> bool:
    """請求是否來自本機。

    只看 socket 對端位址。X-Forwarded-For / X-Real-IP 是使用者可控的標頭，
    拿來判斷權限就等於沒有判斷。
    """
    client = request.client
    if client is None or not client.host:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        # 測試用的 "testclient" 或非 IP 的主機名，一律視為不是本機。
        return False


def require_loopback(request: Request) -> None:
    if not is_loopback(request):
        raise ValidationError(
            "只有本機（127.0.0.1 或 ::1）可以修改 AI 設定。"
            "ItemTrace 沒有登入系統，若讓區網內其他裝置改 API key，"
            "等於開放你的 OpenRouter 帳號。請在本機瀏覽器開啟 /settings。"
        )


def _settings_out(request: Request) -> AiSettingsOut:
    try:
        settings = ai_config.read_settings()
    except AiConfigError as exc:
        # 設定檔壞掉要讓使用者看得見、看得懂，但不能把檔案內容印出來
        raise ValidationError(ai_config.redact(str(exc))) from None
    return AiSettingsOut(
        provider=settings.provider,
        configured=settings.configured,
        model=settings.model,
        default_model=ai_config.DEFAULT_MODEL,
        can_edit=is_loopback(request),
        config_file=f"tools/{ai_config.CONFIG_FILENAME}",
    )


@router.get("/api/settings/ai", response_model=AiSettingsOut)
def get_ai_settings(request: Request) -> AiSettingsOut:
    """讀取設定狀態。

    任何來源都可以讀 —— 回應裡沒有 key，只有「有沒有設定」和 model。
    """
    return _settings_out(request)


@router.post("/api/settings/ai", response_model=AiSettingsSaved)
def update_ai_settings(
    body: AiSettingsUpdate, request: Request
) -> AiSettingsSaved:
    """儲存 model 與／或 API key（僅限本機）。

    `api_key` 留空 → 保留原本的 key。清除是另一個明確的動作。
    """
    require_loopback(request)
    try:
        before = ai_config.read_settings()
        saved = ai_config.save_settings(body.api_key, body.model)
    except AiConfigError as exc:
        raise ValidationError(ai_config.redact(str(exc))) from None

    return AiSettingsSaved(
        provider=saved.provider,
        configured=saved.configured,
        model=saved.model,
        api_key_changed=bool((body.api_key or "").strip()),
        model_changed=saved.model != before.model,
    )


@router.post("/api/settings/ai/clear-key", response_model=AiSettingsSaved)
def clear_ai_key(request: Request) -> AiSettingsSaved:
    """清除 API key，保留 model（僅限本機）。

    密碼欄留白不算清除 —— 那樣按一次儲存就把 key 弄丟了。
    """
    require_loopback(request)
    try:
        saved = ai_config.clear_api_key()
    except AiConfigError as exc:
        raise ValidationError(ai_config.redact(str(exc))) from None
    return AiSettingsSaved(
        provider=saved.provider,
        configured=saved.configured,
        model=saved.model,
        api_key_changed=True,
        model_changed=False,
    )


@router.post("/api/settings/ai/test", response_model=AiApiTestResult)
def test_ai_api(body: AiSettingsUpdate, request: Request) -> AiApiTestResult:
    """用最小文字請求測試 provider（僅限本機）。

    不讀 ItemTrace 商品、不送照片、不建立 suggestion、不修改任何東西 ——
    只確認「這把 key 加上這個 model 能不能通」。

    帶 `api_key` 進來時測的是「剛貼上、還沒存」的那把 key；留空則測已存的。
    """
    require_loopback(request)

    model = (body.model or "").strip()
    incoming = (body.api_key or "").strip()
    try:
        stored = ai_config.load_config()
    except AiConfigError as exc:
        raise ValidationError(ai_config.redact(str(exc))) from None

    api_key = incoming or stored.api_key
    model = model or stored.model

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
    }).encode("utf-8")

    request_object = urllib.request.Request(
        OPENROUTER_ENDPOINT, data=payload, method="POST"
    )
    request_object.add_header("Authorization", "Bearer " + api_key)
    request_object.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(
            request_object, timeout=PROVIDER_TEST_TIMEOUT
        ) as response:
            response.read()
        return AiApiTestResult(ok=True, model=model)
    except urllib.error.HTTPError as exc:
        detail = ai_config.redact(
            exc.read().decode("utf-8", "replace")[:300], api_key
        )
        raise ValidationError(f"API 測試失敗（{exc.code}）：{detail}") from None
    except urllib.error.URLError as exc:
        raise ValidationError(f"API 測試失敗：{exc.reason}") from None
